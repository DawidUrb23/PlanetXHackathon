"""SPHEREx DR1/QR3 via IRSA SIA2. Rejestruje metadane w PostgreSQL.
Opcjonalnie pobiera 1 FITS na dysk serwera, z limitem rozmiaru.
Dodaj w api.py: from fits_api import router as fits_router; app.include_router(fits_router)
Wymaga: requests, astropy, psycopg (jak w obecnym backendzie).
"""
import hashlib
import io
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import requests
from astropy.io.votable import parse_single_table
from astropy.io import fits
from fastapi import APIRouter, HTTPException, Query, Header
from psycopg.rows import dict_row

from nasa_asteroid_service import db_connection

router = APIRouter(prefix="/api/fits", tags=["SPHEREx FITS"])
SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
COLLECTIONS = {"spherex_dr1", "spherex_qr3"}
FITS_DIR = Path(os.getenv("FITS_STORAGE_DIR", "fits_storage")).resolve()
MAX_BYTES = 150 * 1024 * 1024


def require_schema():
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.fits_assets')")
            if cur.fetchone()[0] is None:
                raise HTTPException(status_code=503, detail="Uruchom create_fits_table.sql w PostgreSQL")


def as_text(row, key):
    if key not in row.colnames:
        return None
    value = row[key]
    if getattr(value, "mask", False) is not False:
        try:
            if bool(value.mask):
                return None
        except (AttributeError, ValueError):
            pass
    return None if value is None else str(value)


@router.get('/search')
def search_fits(
    ra: float = Query(..., ge=0, lt=360),
    dec: float = Query(..., ge=-90, le=90),
    radius: float = Query(0.02, gt=0, le=0.1),
    collection: str = Query('spherex_dr1'),
    limit: int = Query(5, ge=1, le=10),
):
    """Wyszukuje pliki pokrywajace obszar; nie sciaga FITS. Limit max 10."""
    if collection not in COLLECTIONS:
        raise HTTPException(status_code=422, detail='collection: spherex_dr1 lub spherex_qr3')
    require_schema()
    params = {
        "COLLECTION": collection,
        "POS": f"CIRCLE {ra:.6f} {dec:.6f} {radius:.6f}",
        "MAXREC": str(limit),
        "RESPONSEFORMAT": "votable",
    }
    try:
        response = requests.get(SIA_URL, params=params, timeout=(6, 25))
        response.raise_for_status()
        table = parse_single_table(io.BytesIO(response.content)).to_table()
    except Exception as exc:
        print('SPHEREX SIA SEARCH ERROR', repr(exc))
        raise HTTPException(status_code=503, detail='IRSA SIA2 nie odpowiedzialo poprawnie')

    found = []
    for row in table[:limit]:
        url = as_text(row, 'access_url')
        if not url or not url.startswith('https://'):
            continue
        found.append({
            'remote_url': url,
            'title': as_text(row, 'obs_title') or as_text(row, 'obs_id'),
            'mime_type': as_text(row, 'access_format'),
            'size_bytes': None,
        })

    with db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            result = []
            for entry in found:
                cur.execute('''INSERT INTO fits_assets
                    (remote_url,collection,ra_center,dec_center,title,mime_type,size_bytes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (remote_url) DO UPDATE SET
                        title=COALESCE(EXCLUDED.title, fits_assets.title)
                    RETURNING id,remote_url,collection,title,status,size_bytes''',
                    (entry['remote_url'],collection,ra,dec,entry['title'],entry['mime_type'],entry['size_bytes']))
                result.append(dict(cur.fetchone()))
        conn.commit()
    return {'source': 'IRSA_SIA2', 'count':len(result),'files':result,
            'note':'Metadane zapisane w PostgreSQL; plikow FITS nie pobrano.'}


@router.get('/list')
def list_fits(limit: int = Query(30,ge=1,le=100)):
    require_schema()
    with db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('''SELECT id,collection,title,remote_url,status,size_bytes,downloaded_at
                           FROM fits_assets ORDER BY id DESC LIMIT %s''',(limit,))
            files=[dict(row) for row in cur.fetchall()]
    return {'count':len(files),'files':files}


def trusted_url(url: str):
    parsed=urlsplit(url)
    return parsed.scheme == 'https' and parsed.hostname == 'irsa.ipac.caltech.edu' and parsed.port in (None,443)


@router.post('/download/{file_id}')
def download_fits(file_id: int, x_admin_key: str | None = Header(default=None)):
    """Pobranie jednego pliku FITS, zabezpieczone kluczem administratora."""
    expected = os.getenv('FITS_ADMIN_KEY')
    if not expected or not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=403, detail='Brak uprawnien do pobierania FITS')
    require_schema()
    with db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute('SELECT id,remote_url,local_path,status FROM fits_assets WHERE id=%s',(file_id,))
            entry=cur.fetchone()
    if not entry:
        raise HTTPException(status_code=404,detail='Nie ma pliku o takim ID')
    if entry['status']=='downloaded' and entry['local_path'] and Path(entry['local_path']).is_file():
        return {'id':file_id,'status':'already_downloaded'}
    url=entry['remote_url']
    if not trusted_url(url):
        raise HTTPException(status_code=400,detail='Ten adres nie jest obslugiwany przez bezpieczny downloader IRSA')
    FITS_DIR.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(url.encode('utf-8')).hexdigest()
    target=FITS_DIR/f'{key}.fits'
    part=FITS_DIR/f'{key}.part'
    try:
        with requests.get(url,stream=True,timeout=(6,35),allow_redirects=False) as resp:
            if resp.is_redirect:
                raise RuntimeError('Przekierowanie do innego hosta: wymagane bezpieczne dopuszczenie adresu')
            resp.raise_for_status()
            content_len=int(resp.headers.get('Content-Length') or 0)
            if content_len>MAX_BYTES:
                raise RuntimeError('Plik za duzy - limit 150 MiB')
            written=0
            with open(part,'wb') as f:
                for chunk in resp.iter_content(chunk_size=1024*1024):
                    if not chunk:continue
                    written+=len(chunk)
                    if written>MAX_BYTES:
                        raise RuntimeError('Plik przekracza 150 MiB')
                    f.write(chunk)
        with fits.open(part,memmap=True,ignore_missing_simple=False) as hdul:
            hdul.verify('exception')
        part.replace(target)
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''UPDATE fits_assets SET status='downloaded',local_path=%s,
                    size_bytes=%s,downloaded_at=NOW() WHERE id=%s''',(str(target),written,file_id))
            conn.commit()
        return {'id':file_id,'status':'downloaded','size_bytes':written,
                'note':'Plik na serwerze; PostgreSQL przechowuje metadane i sciezke.'}
    except Exception as exc:
        print('FITS DOWNLOAD ERROR',repr(exc))
        raise HTTPException(status_code=502,detail=str(exc)[:180])
    finally:
        part.unlink(missing_ok=True)
