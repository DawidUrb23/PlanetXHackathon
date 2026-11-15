"""NASA Space Apps: katalog wspolny dla aplikacji mobilnej.
W api.py: from catalog_api import router as catalog_router
           app.include_router(catalog_router)  # jeden raz
"""
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from nasa_asteroid_service import db_connection, get_asteroids

router = APIRouter(prefix='/api/catalog', tags=['Catalog & NASA'])
NASA_URL = 'https://ssd-api.jpl.nasa.gov/sb_ident.api'
NASA_SBDB_URL = 'https://ssd-api.jpl.nasa.gov/sbdb.api'
NASA_HORIZONS_URL = 'https://ssd.jpl.nasa.gov/api/horizons.api'


def like_pattern(text: str) -> str:
    text = text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return '%' + text + '%'


def ra_to_nasa(value: float) -> str:
    sec = round(value / 15 * 3600, 2) % 86400
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f'{int(h):02d}-{int(m):02d}-{s:05.2f}'


def dec_to_nasa(value: float) -> str:
    sec = round(abs(value) * 3600, 2)
    d, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f'{"-" if value < 0 else ""}{int(d):02d}-{int(m):02d}-{s:05.2f}'


def ra_to_deg(value) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    n = re.findall(r'\d+(?:\.\d+)?', str(value))
    if len(n) != 3:
        raise ValueError(f'Nieznany format RA: {value!r}')
    h, m, s = map(float, n)
    return (h + m / 60 + s / 3600) * 15


def dec_to_deg(value) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    txt = str(value).strip()
    n = re.findall(r'\d+(?:\.\d+)?', txt)
    if len(n) != 3:
        raise ValueError(f'Nieznany format Dec: {value!r}')
    d, m, s = map(float, n)
    return (-1 if txt.startswith(('-', 'M', 'm')) else 1) * (d + m / 60 + s / 3600)


def _angular_sep_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1 = math.radians(ra1), math.radians(dec1)
    r2, d2 = math.radians(ra2), math.radians(dec2)
    cos_val = max(-1.0, min(1.0, math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)))
    return math.degrees(math.acos(cos_val))


# ==============================================================================
# FORMUŁOWANIE ZAPYTAŃ DO NASA JPL (SBDB + HORIZONS) PO NAZWIE OBIEKTU
# ==============================================================================

def _http_get_json(url: str, params: dict, timeout: float = 15.0) -> dict | None:
    query_str = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_str}"
    print(f"[NASA QUERY] GET {full_url}")
    req = urllib.request.Request(
        full_url,
        headers={"User-Agent": "CosmicExplorerAR/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)


def _query_nasa_horizons_position(
    command: str, lat: float = 50.3, lon: float = 18.8, alt_km: float = 0.3
) -> tuple[float | None, float | None, float | None]:
    """Formułuje zapytanie do NASA JPL Horizons API po aktualne współrzędne RA/Dec i jasność Vmag."""
    now = datetime.now(timezone.utc)
    start_str = now.strftime("%Y-%m-%d %H:%M")
    stop_str = (now + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M")

    clean_cmd = command.strip()
    if not clean_cmd.isdigit() and not clean_cmd.endswith(";"):
        clean_cmd = f"{clean_cmd};"

    params = {
        "format": "json",
        "COMMAND": f"'{clean_cmd}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord@399'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{lon:.4f},{lat:.4f},{alt_km:.3f}'",
        "START_TIME": f"'{start_str}'",
        "STOP_TIME": f"'{stop_str}'",
        "STEP_SIZE": "'1m'",
        "QUANTITIES": "'1,9'",
    }

    try:
        data = _http_get_json(NASA_HORIZONS_URL, params, timeout=15.0)
        if not data:
            return None, None, None

        result_txt = data.get("result", "")
        if "$$SOE" not in result_txt or "$$EOE" not in result_txt:
            print("[NASA HORIZONS] Brak bloku $$SOE w odpowiedzi:", result_txt[:300])
            return None, None, None

        ephem_block = result_txt.split("$$SOE")[1].split("$$EOE")[0].strip()
        first_line = ephem_block.splitlines()[0].strip()
        print("[NASA HORIZONS] Ephem line:", first_line)

        match = re.search(
            r"(\d{2}\s+\d{2}\s+\d{2}(?:\.\d+)?)\s+([+-]?\d{2}\s+\d{2}\s+\d{2}(?:\.\d+)?)",
            first_line,
        )
        if not match:
            return None, None, None

        ra_deg = ra_to_deg(match.group(1))
        dec_deg = dec_to_deg(match.group(2))

        tail = first_line[match.end():].split()
        mag = None
        for token in tail:
            try:
                val = float(token)
                if -30.0 <= val <= 35.0:
                    mag = val
                    break
            except ValueError:
                continue

        return ra_deg, dec_deg, mag
    except Exception as exc:
        print("[NASA HORIZONS ERROR]", repr(exc))
        return None, None, None


def _upsert_nasa_search_result(
    name: str, designation: str, object_type: str, description: str, ra: float, dec: float, observed_at: datetime
) -> int:
    """Zapisuje obiekt wyszukany w NASA JPL do celestial_objects oraz observations."""
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM data_sources WHERE source_url=%s LIMIT 1', (NASA_HORIZONS_URL,))
            row = cur.fetchone()
            if row:
                source_id = row[0]
            else:
                cur.execute(
                    'INSERT INTO data_sources (name, provider, source_url) VALUES (%s,%s,%s) RETURNING id',
                    ('NASA JPL Horizons & SBDB', 'NASA JPL', NASA_HORIZONS_URL),
                )
                source_id = cur.fetchone()[0]

            cur.execute('SELECT id FROM celestial_objects WHERE name=%s LIMIT 1', (name,))
            obj_row = cur.fetchone()
            if obj_row:
                obj_id = obj_row[0]
            else:
                cur.execute(
                    'INSERT INTO celestial_objects (name, object_type, nasa_identifier, description) VALUES (%s,%s,%s,%s) RETURNING id',
                    (name, object_type, designation, description),
                )
                obj_id = cur.fetchone()[0]

            cur.execute(
                'INSERT INTO observations (object_id, source_id, observed_at, ra, dec, wavelength_band, data_url) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                (obj_id, source_id, observed_at, ra, dec, 'Ephemeris-Optical', NASA_HORIZONS_URL),
            )
        conn.commit()
    return obj_id


def search_nasa_by_name(query_name: str, lat: float = 50.3, lon: float = 18.8) -> list[dict]:
    """Formułuje zapytanie do NASA JPL SBDB oraz Horizons dla wpisanej frazy (asteroidy, komety, planety)."""
    clean_name = query_name.strip()
    if not clean_name:
        return []

    print(f"[SEARCH NASA] Szukam w NASA dla frazy: {clean_name!r}")
    found_candidates = []

    planet_map = {
        "mercury": ("199", "Mercury", "planet"),
        "merkury": ("199", "Mercury", "planet"),
        "venus": ("299", "Venus", "planet"),
        "wenus": ("299", "Venus", "planet"),
        "moon": ("301", "Moon", "satellite"),
        "ksiezyc": ("301", "Moon", "satellite"),
        "mars": ("499", "Mars", "planet"),
        "jupiter": ("599", "Jupiter", "planet"),
        "jowisz": ("599", "Jupiter", "planet"),
        "saturn": ("699", "Saturn", "planet"),
        "uranus": ("799", "Uranus", "planet"),
        "uran": ("799", "Uranus", "planet"),
        "neptune": ("899", "Neptune", "planet"),
        "neptun": ("899", "Neptune", "planet"),
        "pluto": ("999", "Pluto", "dwarf_planet"),
        "pluton": ("999", "Pluto", "dwarf_planet"),
    }

    key = clean_name.casefold()
    if key in planet_map:
        cmd, canonical, otype = planet_map[key]
        found_candidates.append({
            "name": canonical,
            "designation": cmd,
            "command": cmd,
            "object_type": otype,
            "description": f"Planeta / obiekt Układu Słonecznego ({canonical}, NASA JPL Horizons).",
        })
    else:
        try:
            payload = _http_get_json(NASA_SBDB_URL, {"sstr": clean_name}, timeout=12.0)
            if payload and "object" in payload:
                obj = payload["object"]
                orbit_cls = (obj.get("orbit_class") or {}).get("name", "Small Body")
                fullname = obj.get("fullname") or obj.get("des") or clean_name
                des = str(obj.get("des") or obj.get("spkid") or clean_name)
                found_candidates.append({
                    "name": fullname,
                    "designation": des,
                    "command": des,
                    "object_type": "comet" if str(obj.get("kind", "")).startswith("c") else "asteroid",
                    "description": f"Obiekt NASA JPL SBDB ({orbit_cls}).",
                })
            elif payload and "list" in payload:
                for item in payload["list"][:3]:
                    pdes = str(item.get("pdes") or "").strip()
                    nm = str(item.get("name") or pdes).strip()
                    if pdes:
                        found_candidates.append({
                            "name": nm,
                            "designation": pdes,
                            "command": pdes,
                            "object_type": "asteroid",
                            "description": f"Obiekt dopasowany w NASA JPL SBDB ({pdes}).",
                        })
        except Exception as exc:
            print("[NASA SBDB WARN]", repr(exc))

        if not found_candidates:
            found_candidates.append({
                "name": clean_name,
                "designation": clean_name,
                "command": clean_name,
                "object_type": "celestial_object",
                "description": f"Obiekt z NASA JPL Horizons ({clean_name}).",
            })

    resolved = []
    now_utc = datetime.now(timezone.utc)

    for cand in found_candidates[:2]:
        ra_deg, dec_deg, mag = _query_nasa_horizons_position(cand["command"], lat=lat, lon=lon)
        if ra_deg is None or dec_deg is None:
            continue

        try:
            obj_id = _upsert_nasa_search_result(
                name=cand["name"],
                designation=cand["designation"],
                object_type=cand["object_type"],
                description=cand["description"],
                ra=ra_deg,
                dec=dec_deg,
                observed_at=now_utc,
            )
        except Exception as db_exc:
            print("[DB SAVE WARN]", repr(db_exc))
            obj_id = f"nasa_{cand['designation']}"

        resolved.append({
            "id": str(obj_id),
            "name": cand["name"],
            "designation": cand["designation"],
            "object_type": cand["object_type"],
            "description": cand["description"],
            "ra": ra_deg,
            "dec": dec_deg,
            "observed_at": now_utc.isoformat(),
            "magnitude": mag if mag is not None else 13.5,
            "images": [],
            "data_source": "nasa_jpl_horizons",
            "position_current": True,
        })

    print(f"[SEARCH NASA] Zwracam {len(resolved)} obiektów z NASA.")
    return resolved


# ==============================================================================
# PRZESZUKIWANIE LOKALNYCH TABEL POSTGRESQL
# ==============================================================================

def _cache_objects(cur, max_items=100):
    """Tylko rozpoznawalne asteroidowe rekordy z cache JSONB."""
    cur.execute("""
        SELECT response_data, fetched_at
        FROM asteroid_cache
        WHERE expires_at > NOW()
        ORDER BY fetched_at DESC
        LIMIT 30
    """)
    found = {}
    for record in cur.fetchall():
        raw = record['response_data'] or {}
        if not isinstance(raw, dict):
            continue
        data = raw.get('data', raw)
        if not isinstance(data, dict):
            continue
        for item in data.get('objects', []):
            if not isinstance(item, dict) or not item.get('name'):
                continue
            try:
                ra = ra_to_deg(item['ra'])
                dec = dec_to_deg(item['dec'])
            except (KeyError, ValueError, TypeError, IndexError):
                continue
            name = str(item['name']).strip()
            key = name.casefold()
            if key in found:
                continue
            try:
                magnitude = float(item['magnitude']) if item.get('magnitude') is not None else None
            except (ValueError, TypeError):
                magnitude = None
            found[key] = {
                'id': f'cache:{key}',
                'name': name,
                'designation': name,
                'object_type': 'asteroid',
                'description': 'Asteroida NASA JPL (cache)',
                'ra': ra,
                'dec': dec,
                'observed_at': record['fetched_at'].isoformat() if record['fetched_at'] else None,
                'magnitude': magnitude,
                'images': [],
                'data_source': 'asteroid_cache',
                'position_current': False,
            }
            if len(found) >= max_items:
                return list(found.values())
    return list(found.values())


def _detail_images(cur, names):
    """Uzupelnij fotografie z cache szczegolow bez udawania pozycji orbitalnej."""
    cur.execute("""SELECT lookup_key, response_data FROM asteroid_details_cache
                   ORDER BY fetched_at DESC LIMIT 100""")
    by_name = {str(n).casefold(): n for n in names}
    result = {}
    for row in cur.fetchall():
        data = row['response_data']
        if not isinstance(data, dict):
            continue
        labels = [str(row['lookup_key']), str(data.get('name') or ''), str(data.get('designation') or '')]
        keys = [x.casefold() for x in labels if x]
        images = []
        for image in data.get('images', [])[:10]:
            if isinstance(image, dict) and isinstance(image.get('url'), str):
                images.append({'title': image.get('title') or 'NASA', 'url': image['url']})
        for key in keys:
            if key in by_name and images:
                result[key] = images
    return result


def _featured_rows(cur):
    """Katalog znanych celow (w tym planety i asteroidy) z ich wspolrzednymi RA/Dec."""
    cur.execute("SELECT to_regclass('public.featured_sky_objects')")
    if next(iter(cur.fetchone().values())) is None:
        return []
    cur.execute("""SELECT object_key, name, designation, object_type, is_moving,
                          ra_deg, dec_deg, image_url, image_source_url
                   FROM featured_sky_objects
                   ORDER BY (ra_deg IS NOT NULL AND dec_deg IS NOT NULL) DESC, object_key""")
    result = []
    for obj in cur.fetchall():
        images = [{'title': obj['name'], 'url': obj['image_url']}] if obj['image_url'] else []
        result.append({
            'id': f"featured:{obj['object_key']}",
            'name': obj['name'],
            'designation': obj['designation'],
            'object_type': obj['object_type'],
            'description': 'Wyróżniony obiekt astronomiczny',
            'ra': obj['ra_deg'],
            'dec': obj['dec_deg'],
            'observed_at': None,
            'magnitude': 12.0 if obj['ra_deg'] is not None else None,
            'images': images,
            'data_source': 'featured_sky_objects',
            'position_current': not bool(obj['is_moving']),
            'image_source_url': obj['image_source_url'],
        })
    return result


def _list_db(name=None, ra=None, dec=None, radius=15, limit=50):
    if (ra is None) != (dec is None):
        raise HTTPException(status_code=422, detail='Podaj oba parametry ra i dec')

    where = []
    params = []
    terms = (name or '').split()

    for term in terms:
        pat = like_pattern(term)
        where.append('''(o.name ILIKE %s OR o.nasa_identifier ILIKE %s
                   OR o.description ILIKE %s OR o.object_type ILIKE %s
                   OR EXISTS (SELECT 1 FROM images z WHERE z.object_id=o.id AND z.title ILIKE %s))''')
        params.extend([pat] * 5)

    if ra is not None:
        where.append('''obs.ra IS NOT NULL AND obs.dec IS NOT NULL AND
            degrees(acos(least(1, greatest(-1,
            sin(radians(obs.dec))*sin(radians(%s))+
            cos(radians(obs.dec))*cos(radians(%s))*cos(radians(obs.ra-%s)) ))))<=%s''')
        params.extend([dec, dec, ra, radius])

    sql = '''SELECT o.id, o.name, o.nasa_identifier AS designation, o.object_type, o.description,
                    obs.ra, obs.dec, obs.observed_at, COALESCE(imgs.images, '[]'::json) AS images
             FROM celestial_objects o
             LEFT JOIN LATERAL (
                 SELECT ra, dec, observed_at FROM observations
                 WHERE object_id=o.id AND ra IS NOT NULL AND dec IS NOT NULL
                 ORDER BY observed_at DESC NULLS LAST, id DESC LIMIT 1
             ) obs ON TRUE
             LEFT JOIN LATERAL (
                 SELECT json_agg(json_build_object('title', title, 'url', image_url) ORDER BY id) AS images
                 FROM (SELECT id, title, image_url FROM images WHERE object_id=o.id ORDER BY id LIMIT 10) i
             ) imgs ON TRUE'''
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY o.id DESC LIMIT %s'
    params.append(limit)

    combined = []
    with db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # 1. Wyróżniony katalog featured_sky_objects
            for f in _featured_rows(cur):
                if terms:
                    haystack = f"{f['name']} {f['designation']} {f['object_type']}".casefold()
                    if not all(t.casefold() in haystack for t in terms):
                        continue
                if ra is not None:
                    if f['ra'] is None or f['dec'] is None:
                        continue
                    if _angular_sep_deg(ra, dec, f['ra'], f['dec']) > radius:
                        continue
                combined.append(f)

            # 2. Tabela celestial_objects
            cur.execute(sql, params)
            for r in cur.fetchall():
                combined.append({
                    'id': str(r['id']),
                    'name': r['name'] or r['designation'] or f"Obiekt {r['id']}",
                    'designation': r['designation'] or '',
                    'object_type': r['object_type'] or 'celestial_object',
                    'description': r['description'] or 'Brak opisu w bazie',
                    'ra': r['ra'],
                    'dec': r['dec'],
                    'observed_at': r['observed_at'].isoformat() if r['observed_at'] else None,
                    'magnitude': None,
                    'images': r['images'] or [],
                    'data_source': 'celestial_objects',
                    'position_current': False,
                })

            # 3. Tabela asteroid_cache
            if len(combined) < limit:
                for c in _cache_objects(cur, max_items=200):
                    if terms and not all(t.casefold() in c['name'].casefold() for t in terms):
                        continue
                    if ra is not None and _angular_sep_deg(ra, dec, c['ra'], c['dec']) > radius:
                        continue
                    combined.append(c)

            if combined:
                more_images = _detail_images(cur, [o['name'] for o in combined])
                for obj in combined:
                    if not obj['images']:
                        obj['images'] = more_images.get(obj['name'].casefold(), [])

    unique = []
    seen = set()
    for item in combined:
        key = item['name'].casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique[:limit]


# ==============================================================================
# ENDPOINTY FASTAPI
# ==============================================================================

@router.get('/objects')
def get_catalog_objects(
    name: str | None = Query(None, max_length=100),
    ra: float | None = Query(None, ge=0, lt=360),
    dec: float | None = Query(None, ge=-90, le=90),
    radius: float = Query(15, gt=0, le=180),
    limit: int = Query(50, ge=1, le=200),
    lat: float = Query(50.3, ge=-90, le=90),
    lon: float = Query(18.8, ge=-180, le=180),
    query_nasa: bool = Query(False),
):
    try:
        rows = _list_db(name, ra, dec, radius, limit)
        source_tag = 'local_db'

        if name and query_nasa:
            nasa_hits = search_nasa_by_name(name, lat=lat, lon=lon)
            if nasa_hits:
                source_tag = 'nasa_jpl_and_local_db'
                merged = []
                nasa_by_key = {n['name'].casefold(): n for n in nasa_hits}
                for n in nasa_hits:
                    local_match = next((r for r in rows if r['name'].casefold() == n['name'].casefold()), None)
                    if local_match and local_match.get('images'):
                        n['images'] = local_match['images']
                    merged.append(n)
                for r in rows:
                    if r['name'].casefold() not in nasa_by_key:
                        merged.append(r)
                rows = merged[:limit]

        return {'source': source_tag, 'count': len(rows), 'asteroids': rows}
    except HTTPException:
        raise
    except Exception as exc:
        print('CATALOG OBJECTS ERROR', repr(exc))
        raise HTTPException(status_code=500, detail='Blad odczytu katalogu')


@router.get('/objects/details')
def get_catalog_object_details(
    name: str = Query(..., min_length=1, max_length=100),
    lat: float = Query(50.3, ge=-90, le=90),
    lon: float = Query(18.8, ge=-180, le=180),
):
    try:
        rows = _list_db(name=name, limit=20)
        if not rows:
            rows = search_nasa_by_name(name, lat=lat, lon=lon)
        if not rows:
            raise HTTPException(status_code=404, detail='Brak obiektu w bazie oraz w NASA JPL')
        exact = next(
            (o for o in rows if o['name'].casefold() == name.casefold() or o['designation'].casefold() == name.casefold()),
            None,
        )
        return exact or rows[0]
    except HTTPException:
        raise
    except Exception as exc:
        print('CATALOG DETAILS ERROR', repr(exc))
        raise HTTPException(status_code=500, detail='Blad odczytu szczegolow')


@router.get('/all')
def get_all_catalog_objects(
    limit: int = Query(1000, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    include_cache: bool = Query(True),
    include_featured: bool = Query(True),
):
    """Jeden JSON z katalogu, cache i katalogu 100 obiektow."""
    try:
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                objects = []

                if include_featured:
                    objects.extend(_featured_rows(cur))

                cur.execute("""SELECT o.id, o.name, o.nasa_identifier AS designation,
                                      o.object_type, o.description, obs.ra, obs.dec, obs.observed_at,
                                      COALESCE(imgs.images, '[]'::json) AS images
                               FROM celestial_objects o
                               LEFT JOIN LATERAL (
                                   SELECT ra, dec, observed_at FROM observations
                                   WHERE object_id=o.id AND ra IS NOT NULL AND dec IS NOT NULL
                                   ORDER BY observed_at DESC NULLS LAST, id DESC LIMIT 1
                               ) obs ON TRUE
                               LEFT JOIN LATERAL (
                                   SELECT json_agg(json_build_object('title', title, 'url', image_url) ORDER BY id) images
                                   FROM (SELECT id, title, image_url FROM images WHERE object_id=o.id
                                         ORDER BY id LIMIT 10) q
                               ) imgs ON TRUE
                               ORDER BY o.id""")
                rows = cur.fetchall()
                existing = {o['name'].casefold() for o in objects if o.get('ra') is not None}

                for r in rows:
                    obj_name = r['name'] or r['designation'] or f"Obiekt {r['id']}"
                    if obj_name.casefold() in existing:
                        continue
                    objects.append({
                        'id': str(r['id']),
                        'name': obj_name,
                        'designation': r['designation'] or '',
                        'object_type': r['object_type'] or 'celestial_object',
                        'description': r['description'] or 'Brak opisu',
                        'ra': r['ra'],
                        'dec': r['dec'],
                        'observed_at': r['observed_at'].isoformat() if r['observed_at'] else None,
                        'magnitude': None,
                        'images': r['images'] or [],
                        'data_source': 'celestial_objects',
                        'position_current': False,
                    })
                    existing.add(obj_name.casefold())

                if include_cache:
                    cache = _cache_objects(cur, max_items=300)
                    objects.extend(x for x in cache if x['name'].casefold() not in existing)
                    more_images = _detail_images(cur, [o['name'] for o in objects])
                    for obj in objects:
                        if not obj['images']:
                            obj['images'] = more_images.get(obj['name'].casefold(), [])

                spectral = []
                if include_cache:
                    cur.execute("SELECT to_regclass('public.spherex_cache')")
                    if next(iter(cur.fetchone().values())) is not None:
                        cur.execute("""SELECT response_data, fetched_at FROM spherex_cache
                                       ORDER BY fetched_at DESC LIMIT 30""")
                        for rec in cur.fetchall():
                            raw = rec['response_data'] or {}
                            d = raw.get('data', raw) if isinstance(raw, dict) else {}
                            if not isinstance(d, dict):
                                continue
                            target = d.get('target') or {}
                            spectral.append({
                                'target': target,
                                'observation_count': len(d.get('observations') or []),
                                'fetched_at': rec['fetched_at'].isoformat() if rec['fetched_at'] else None,
                            })

        result = objects[offset:offset + limit]
        return {
            'source': 'postgresql_combined',
            'count': len(result),
            'total': len(objects),
            'offset': offset,
            'limit': limit,
            'has_more': offset + limit < len(objects),
            'asteroids': result,
            'spherex_observation_groups': spectral,
            'note': 'Pole asteroids zawiera rozne typy obiektow, nie tylko asteroidy; pozycje z bazy moga byc historyczne.',
        }
    except Exception as exc:
        print('COMBINED CATALOG ERROR:', repr(exc))
        raise HTTPException(status_code=500, detail='Blad odczytu katalogu')


def save_nasa_objects(objects, observation_time):
    ids = {}
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM data_sources WHERE source_url=%s LIMIT 1', (NASA_URL,))
            row = cur.fetchone()
            if row:
                source_id = row[0]
            else:
                cur.execute(
                    'INSERT INTO data_sources (name, provider, source_url) VALUES (%s,%s,%s) RETURNING id',
                    ('NASA JPL Small-Body Identification', 'NASA JPL', NASA_URL),
                )
                source_id = cur.fetchone()[0]
            for obj in objects:
                name = str(obj['name']).strip()
                ra, dec = ra_to_deg(obj['ra']), dec_to_deg(obj['dec'])
                cur.execute("SELECT id FROM celestial_objects WHERE name=%s AND object_type='asteroid' LIMIT 1", (name,))
                row = cur.fetchone()
                if row:
                    obj_id = row[0]
                else:
                    cur.execute(
                        "INSERT INTO celestial_objects (name, object_type, nasa_identifier, description) VALUES (%s,'asteroid',%s,%s) RETURNING id",
                        (name, name, 'Asteroida NASA JPL'),
                    )
                    obj_id = cur.fetchone()[0]
                cur.execute(
                    'SELECT id FROM observations WHERE object_id=%s AND source_id=%s AND observed_at=%s LIMIT 1',
                    (obj_id, source_id, observation_time),
                )
                if not cur.fetchone():
                    cur.execute(
                        'INSERT INTO observations (object_id, source_id, observed_at, ra, dec, wavelength_band, data_url) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                        (obj_id, source_id, observation_time, ra, dec, 'Optical-V', NASA_URL),
                    )
                ids[name] = obj_id
        conn.commit()
    return ids




@router.get("/scan-or-fetch")
def scan_or_fetch_sky(
    ra: float = Query(..., ge=0, lt=360),
    dec: float = Query(..., ge=-90, le=90),
    radius: float = Query(15, gt=0, le=30),
    lat: float = Query(50.3, ge=-90, le=90),
    lon: float = Query(18.8, ge=-180, le=180),
    alt_km: float = Query(0.3),
    limit: int = Query(20, ge=1, le=20),
    always_fetch_nasa: bool = Query(False),
    fetch_spherex: bool = Query(False),
):
    now = datetime.now(timezone.utc)

    observed = now.replace(
        minute=(now.minute // 5) * 5,
        second=0,
        microsecond=0
    )

    print(
        f"SCAN: RA={ra}, Dec={dec}, "
        f"radius={radius}, force_nasa={always_fetch_nasa}",
        flush=True
    )

    # ==========================================
    # 1. SPRAWDZAMY LOKALNA BAZE
    # ==========================================

    try:
        local_objects = _list_db(
            ra=ra,
            dec=dec,
            radius=radius,
            limit=limit
        )

    except Exception as exc:
        print("POSTGRES ERROR:", repr(exc), flush=True)

        raise HTTPException(
            status_code=500,
            detail="Blad odczytu PostgreSQL"
        ) from exc

    print(
        f"POSTGRES: znaleziono {len(local_objects)} obiektow",
        flush=True
    )

    # Jesli mamy obiekty i nie wymuszamy NASA,
    # zwracamy dane bez wykonywania nowego zapytania.
    if local_objects and not always_fetch_nasa:

        print("CACHE HIT - dane z PostgreSQL", flush=True)

        return {
            "source": "local_db",
            "count": len(local_objects),
            "asteroids": local_objects,
            "observation_time": observed.isoformat(),
            "nasa_queried": False,
            "stale": True,
            "spherex_status": "not_requested"
        }

    # ==========================================
    # 2. BRAK OBIEKTOW LUB WYMUSZONE NASA
    # ==========================================

    print(
        "NASA FETCH - pobieram dane z NASA JPL",
        flush=True
    )

    try:
        response = get_asteroids(
            latitude=lat,
            longitude=lon,
            altitude_km=alt_km,
            observation_time=observed,
            ra_center=ra_to_nasa(ra),
            dec_center=dec_to_nasa(dec),
            ra_half_width=min(max(radius / 2, 0.5), 2.5),
            dec_half_width=min(max(radius / 2, 0.5), 2.5),
            magnitude_limit=17.5
        )

        data = response.get("data", {})
        nasa_objects = data.get("objects", [])

        # Maksymalnie 20 wynikow
        selected = sorted(
            nasa_objects,
            key=lambda x: float(
                x.get("distance_from_center_deg")
                if x.get("distance_from_center_deg") is not None
                else 1e9
            )
        )[:limit]

        print(
            f"NASA: znaleziono {len(selected)} asteroid",
            flush=True
        )

        # ======================================
        # 3. ZAPIS DANYCH DO POSTGRESQL
        # ======================================

        ids = (
            save_nasa_objects(selected, observed)
            if selected else {}
        )

        items = []

        for obj in selected:
            name = str(obj["name"]).strip()

            items.append({
                "id": str(ids[name]),
                "name": name,
                "designation": name,
                "object_type": "asteroid",
                "description": "Asteroida NASA JPL",
                "ra": ra_to_deg(obj["ra"]),
                "dec": dec_to_deg(obj["dec"]),
                "sep_deg": obj.get(
                    "distance_from_center_deg"
                ),
                "magnitude": obj.get("magnitude"),
                "images": [],
                "observed_at": observed.isoformat(),
                "data_source": response.get(
                    "source", "nasa"
                ),
                "position_current": (
                    response.get("source") != "cache"
                )
            })

        print(
            f"POSTGRES: zapisano/odswiezono "
            f"{len(items)} asteroid",
            flush=True
        )

        return {
            "source": response.get("source", "nasa"),
            "count": len(items),
            "asteroids": items,
            "observation_time": observed.isoformat(),
            "nasa_queried": True,
            "stale": response.get("source") == "cache",
            "spherex_status": (
                "separate_endpoint"
                if fetch_spherex
                else "not_requested"
            )
        }

    # ==========================================
    # 4. AWARIA NASA - DANE LOKALNE
    # ==========================================

    except Exception as exc:

        print("NASA FETCH ERROR:", repr(exc), flush=True)

        if local_objects:

            print(
                "NASA OFFLINE - zwracam PostgreSQL",
                flush=True
            )

            return {
                "source": "local_fallback_stale",
                "count": len(local_objects),
                "asteroids": local_objects,
                "observation_time": observed.isoformat(),
                "nasa_queried": True,
                "stale": True,
                "spherex_status": "not_requested"
            }

        raise HTTPException(
            status_code=503,
            detail="NASA JPL niedostepna i brak danych lokalnych"
        ) from exc
