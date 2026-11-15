"""Katalog znanych obiektow astronomicznych dla aplikacji AR.

W api.py (jeden raz):
    from featured_api import router as featured_router
    app.include_router(featured_router)

GET /api/catalog/featured?lat=50.3&lon=18.8

Wspolrzedne planet (zmiennych obiektow) sa wyliczane dla aktualnego
czasu i lokalizacji obserwatora, a nie pobierane ze statycznych pol
ra_deg/dec_deg w PostgreSQL. Uklad dynamicznych RA/Dec: CIRS (pozorne).
Dla obiektow stalych: RA/Dec ICRS/J2000 z katalogu.
Aplikacja AR powinna korzystac z azimuth/altitude, jezeli chce wyswietlic
obiekty w lokalnym kierunku nieba; RA/Dec wymagaja zgodnej konwersji.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from nasa_asteroid_service import db_connection

router = APIRouter(prefix="/api/catalog", tags=["Featured sky"])

# Nazwy rozpoznawane przez wbudowane efemerydy Astropy.
SOLAR_SYSTEM_NAMES = {
    "mercury", "venus", "mars", "jupiter", "saturn", "uranus",
    "neptune", "sun", "moon",
}


@router.get("/featured")
def featured_objects(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    alt_m: float = Query(0.0, ge=-500, le=10000),
):
    """Zwraca katalog z pozycjami dla podanego miejsca i aktualnego czasu.

    Zwrotne `objects` i `asteroids` zawieraja te same rekordy dla zgodnosci
    z istniejacymi wersjami aplikacji mobilnej. Brak pozycji to null.
    """
    try:
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("""
                    SELECT object_key, name, designation, object_type,
                           is_moving, ra_deg, dec_deg, image_url,
                           image_source_url, image_verified
                    FROM featured_sky_objects
                    ORDER BY object_key
                """)
                items = cur.fetchall()
    except Exception as exc:
        print("FEATURED DATABASE ERROR:", repr(exc))
        raise HTTPException(status_code=500, detail="Blad odczytu katalogu PostgreSQL") from exc

    try:
        import astropy.units as u
        from astropy.coordinates import (
            SkyCoord, EarthLocation, AltAz, CIRS, get_body,
            solar_system_ephemeris,
        )
        from astropy.time import Time
        from astropy.utils import iers

        # Nie probuj pobierac zewnetrznych tablic IERS podczas zadania HTTP.
        iers.conf.auto_download = False
        observation_time = datetime.now(timezone.utc)
        astro_time = Time(observation_time)
        location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=alt_m * u.m)
        horizontal_frame = AltAz(obstime=astro_time, location=location)
        apparent_frame = CIRS(obstime=astro_time, location=location)

        # Wbudowane efemerydy nie wymagaja sieci NASA w trakcie zapytania.
        # Pluto nie jest w tym wariancie obliczany, wiec pozostanie null.
        with solar_system_ephemeris.set("builtin"):
            output = []
            for item in items:
                item = dict(item)
                key = item["object_key"]
                is_moving = bool(item["is_moving"])

                ra = None if is_moving else item["ra_deg"]
                dec = None if is_moving else item["dec_deg"]
                az = None
                altitude = None
                ra_dec_frame = "CIRS" if is_moving else "ICRS"

                try:
                    if is_moving and key in SOLAR_SYSTEM_NAMES:
                        sky_coord = get_body(key, astro_time, location)
                        # Planety: wspolrzedne POZORNE w CIRS dla obserwatora.
                        apparent = sky_coord.transform_to(apparent_frame)
                        ra = float(apparent.ra.deg)
                        dec = float(apparent.dec.deg)
                    elif not is_moving and ra is not None and dec is not None:
                        sky_coord = SkyCoord(ra=float(ra) * u.deg,
                                             dec=float(dec) * u.deg, frame="icrs")
                        ra = float(ra)
                        dec = float(dec)
                    else:
                        sky_coord = None

                    if sky_coord is not None:
                        horizontal = sky_coord.transform_to(horizontal_frame)
                        az = round(float(horizontal.az.deg), 5)
                        altitude = round(float(horizontal.alt.deg), 5)
                except Exception as exc:
                    print("FEATURED POSITION ERROR:", key, repr(exc))
                    # Nie wymyslamy wspolrzednych, jezeli transformacja zawiodla.
                    if is_moving:
                        ra, dec = None, None
                    az, altitude = None, None

                image_url = item["image_url"]
                images = ([{"title": item["name"], "url": image_url}]
                          if image_url else [])
                output.append({
                    "id": str(key),
                    "name": item["name"],
                    "designation": item["designation"],
                    "object_type": item["object_type"],
                    "description": "Obiekt z katalogu wyroznionych celow astronomicznych",
                    "moving": is_moving,
                    "ra": ra,
                    "dec": dec,
                    "ra_dec_frame": ra_dec_frame,
                    "azimuth": az,
                    "altitude": altitude,
                    "visible_above_horizon": altitude >= 0 if altitude is not None else None,
                    "magnitude": None,
                    "image_url": image_url,
                    "images": images,
                    "image_source_url": item["image_source_url"],
                    "image_verified": item["image_verified"],
                    "data_source": "featured_sky_objects",
                    "position_current": (ra is not None and dec is not None) if is_moving else False,
                    "observed_at": observation_time.isoformat() if is_moving and ra is not None else None,
                })
    except Exception as exc:
        print("FEATURED CALCULATION ERROR:", repr(exc))
        raise HTTPException(status_code=500, detail="Blad obliczania polozenia obiektow") from exc

    return {
        "source": "postgresql+astropy",
        "observation_time": observation_time.isoformat(),
        "observer": {"lat": lat, "lon": lon, "alt_m": alt_m},
        "count": len(output),
        "objects": output,
        "asteroids": output,  # kompatybilnosc ze starszym parserem Androida
        "note": ("Ciala ruchome: pozorne RA/Dec w CIRS; obiekty stale: ICRS/J2000. "
                 "Pluton bez pozycji. Niezweryfikowane zdjecia moga byc niedopasowane. "
                 "Do precyzyjnego AR uzywaj azimuth/altitude i uwzglednij kalibracje czujnikow."),
    }
