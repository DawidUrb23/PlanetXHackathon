
import os
import uuid
import hashlib
from pathlib import Path
from threading import Lock
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import imageio.v2 as imageio
import astropy.units as u

from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
from astropy.nddata import Cutout2D
from astropy.visualization import (
    ImageNormalize,
    PercentileInterval,
    AsinhStretch,
)

from reproject import reproject_interp

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from psycopg.rows import dict_row

from nasa_asteroid_service import db_connection
from fits_object_api import (
    find_object,
    get_object_files,
    index_object_fits,
)
from fits_api import download_fits

router = APIRouter(
    prefix="/api/gifs",
    tags=["GIF from FITS"]
)

ROOT = Path("gif_cache").resolve()
ROOT.mkdir(exist_ok=True)

JOBS = {}
POOL = ThreadPoolExecutor(max_workers=1)
LOCK = Lock()
MAX_FILES = 4


# Znajdz obserwacje wybranego obiektu
def source_files(name):
    obj = find_object(name)
    rows = get_object_files(obj["ref"])

    if len(rows) < 2:
        index_object_fits(
            name=name,
            limit=8,
            x_admin_key=os.getenv("FITS_ADMIN_KEY")
        )
        rows = get_object_files(obj["ref"])

    # Nie mieszamy roznych pasm w jednym timelapse
    by_band = {}

    for row in rows:
        band = row.get("wavelength_band") or "unknown"
        by_band.setdefault(band, []).append(row)

    groups = [
        group for group in by_band.values()
        if len(group) >= 2
    ]

    if not groups:
        raise ValueError(
            "Brak minimum 2 obserwacji w tym samym pasmie"
        )

    files = sorted(
        max(groups, key=len),
        key=lambda r: r.get("observed_at") or ""
    )

    return obj, files[-MAX_FILES:]


# Pobierz brakujacy FITS lub uzyj cache
def local_fits_path(item):
    file_id = int(item["id"])

    download_fits(
        file_id=file_id,
        x_admin_key=os.getenv("FITS_ADMIN_KEY")
    )

    with db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT local_path FROM fits_assets WHERE id=%s",
                (file_id,)
            )
            row = cur.fetchone()

    if not row or not row["local_path"]:
        raise RuntimeError("Brak sciezki FITS")

    path = Path(row["local_path"]).resolve()

    if not path.is_file():
        raise RuntimeError("Nie znaleziono FITS na dysku")

    return path


# Wytnij fragment obrazu wokol obiektu
def read_cutout(path, ra, dec):
    with fits.open(path, memmap=True) as hdul:
        hdu = hdul["IMAGE"] if "IMAGE" in hdul else hdul[0]

        if hdu.data is None:
            raise ValueError("Brak obrazu w FITS")

        data = np.squeeze(hdu.data)

        if data.ndim != 2:
            raise ValueError("FITS nie jest obrazem 2D")

        wcs = WCS(hdu.header).celestial

        if not wcs.has_celestial:
            raise ValueError("Brak WCS")

        position = SkyCoord(
            ra * u.deg,
            dec * u.deg,
            frame="icrs"
        )

        cut = Cutout2D(
            data,
            position=position,
            size=(256, 256),
            wcs=wcs,
            mode="partial",
            fill_value=np.nan,
            copy=True
        )

        return np.asarray(
            cut.data, dtype=np.float32
        ), cut.wcs


# Wykorzystanie algorytmu kolegi:
# wyrownanie WCS + AsinhStretch
def make_gif(obj, items, out_path):
    images = []
    reference_wcs = None

    for item in items:
        img, wcs = read_cutout(
            local_fits_path(item),
            obj["ra"],
            obj["dec"]
        )

        if reference_wcs is None:
            reference_wcs = wcs
            aligned = img
        else:
            aligned, footprint = reproject_interp(
                (img, wcs),
                reference_wcs,
                shape_out=(256, 256)
            )

            aligned = np.where(
                footprint > 0,
                aligned,
                np.nan
            )

        images.append(aligned)

    valid = images[0][np.isfinite(images[0])]

    if valid.size == 0:
        raise ValueError("Brak poprawnych pikseli")

    low, high = PercentileInterval(
        99.5
    ).get_limits(valid)

    if high <= low:
        raise ValueError("Obraz ma zerowy kontrast")

    norm = ImageNormalize(
        vmin=low,
        vmax=high,
        stretch=AsinhStretch(a=0.05)
    )

    result = []
    ref_median = float(np.nanmedian(images[0]))

    for img in images:
        median = float(np.nanmedian(img))

        if np.isfinite(median):
            img = img - (median - ref_median)

        clean = np.where(
            np.isfinite(img),
            img,
            low
        )

        frame = (
            np.clip(norm(clean), 0, 1) * 255
        ).astype(np.uint8)

        result.append(frame)

    imageio.mimsave(
        out_path,
        result,
        duration=0.2,
        loop=0,
        format="GIF"
    )


# Przetwarzanie poza zadaniem HTTP
def process(job_id, name):
    try:
        JOBS[job_id]["status"] = "running"

        obj, files = source_files(name)

        key = hashlib.sha256(
            obj["ref"].encode()
        ).hexdigest()[:16]

        ids = "_".join(str(f["id"]) for f in files)

        cached = ROOT / f"{key}_{ids}.gif"

        if not cached.is_file():
            temporary = ROOT / f"{job_id}.part.gif"

            try:
                make_gif(obj, files, temporary)
                temporary.replace(cached)
            finally:
                temporary.unlink(missing_ok=True)

        JOBS[job_id].update(
            status="done",
            file=str(cached),
            count=len(files)
        )

    except Exception as exc:
        print("GIF ERROR:", repr(exc))

        JOBS[job_id].update(
            status="error",
            error=str(exc)[:200]
        )


# Telefon zamawia wygenerowanie animacji
@router.post("/jobs", status_code=202)
def create_gif_job(
    name: str = Query(..., min_length=1, max_length=160)
):
    with LOCK:
        if any(
            j["status"] in ("queued", "running")
            for j in JOBS.values()
        ):
            raise HTTPException(
                429,
                "Serwer przetwarza juz animacje"
            )

        job_id = uuid.uuid4().hex

        JOBS[job_id] = {
            "status": "queued",
            "name": name
        }

    POOL.submit(process, job_id, name)

    return {
        "job_id": job_id,
        "status": "queued"
    }


# Sprawdzanie postepu
@router.get("/jobs/{job_id}")
def gif_job_status(job_id: str):
    job = JOBS.get(job_id)

    if job is None:
        raise HTTPException(
            404, "Nie znaleziono zadania"
        )

    return {
        "status": job["status"],
        "count": job.get("count"),
        "error": job.get("error"),
        "gif_url": (
            f"/api/gifs/jobs/{job_id}/file"
            if job["status"] == "done"
            else None
        )
    }


# Binarny strumien GIF do telefonu
@router.get("/jobs/{job_id}/file")
def gif_file(job_id: str):
    job = JOBS.get(job_id)

    if not job or job["status"] != "done":
        raise HTTPException(
            404, "GIF nie jest jeszcze gotowy"
        )

    path = Path(job["file"])

    if not path.is_file():
        raise HTTPException(404, "Brak GIF")

    def chunks():
        with path.open("rb") as file:
            while chunk := file.read(65536):
                yield chunk

    return StreamingResponse(
        chunks(),
        media_type="image/gif",
        headers={
            "Content-Disposition":
                'inline; filename="animation.gif"',
            "Cache-Control": "public, max-age=3600"
        }
    )
