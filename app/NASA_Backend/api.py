
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

from nasa_asteroid_service import get_asteroids
from asteroid_details_service import get_asteroid_details
from catalog_api import router as catalog_router


app = FastAPI(title="NASA Space Apps API")


# --------------------------------------------------
# 1. Sprawdzenie działania serwera
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "status": "online",
        "message": "NASA Space Apps API dziala!"
    }


# --------------------------------------------------
# 2. Wyszukiwanie asteroid w polu widzenia
# --------------------------------------------------

@app.get("/api/asteroids")
def asteroids(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    ra_center: str = "03-00-00",
    dec_center: str = "20-00-00",
    altitude_km: float = 0.3,
    ra_half_width: float = Query(1.0, gt=0, le=5),
    dec_half_width: float = Query(1.0, gt=0, le=5),
    magnitude_limit: float = Query(20.0, ge=-5, le=25),
    observation_time: datetime | None = None
):
    if observation_time is None:
        observation_time = datetime.now(timezone.utc)

    if observation_time.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail="Czas musi zawierac strefe czasowa"
        )

    try:
        return get_asteroids(
            latitude=latitude,
            longitude=longitude,
            altitude_km=altitude_km,
            observation_time=observation_time,
            ra_center=ra_center,
            dec_center=dec_center,
            ra_half_width=ra_half_width,
            dec_half_width=dec_half_width,
            magnitude_limit=magnitude_limit
        )

    except Exception as exc:
        print("SPHEREX ERROR:", repr(exc))

        raise HTTPException(
             status_code=503,
             detail={
                 "error": "SPHEREX_UNAVAILABLE",
                "message": "Archiwum NASA IRSA jest chwilowo niedostepne.",
                "retryable": True
            }
    )


# --------------------------------------------------
# 3. Szczegoly asteroidy: opis, parametry i zdjecia
# --------------------------------------------------

@app.get("/api/asteroids/details")
def asteroid_details(
    name: str = Query(..., min_length=2, max_length=100)
):
    try:
        return get_asteroid_details(name)

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc)
        )

    except Exception as exc:
        print("Blad szczegolow:", repr(exc))
        raise HTTPException(
            status_code=502,
            detail="Nie udalo sie pobrac szczegolow"
        )


# --------------------------------------------------
# 4. Konwersja wspolrzednych RA i Dec
# --------------------------------------------------

def ra_to_nasa(ra):
    total_seconds = round(ra / 15.0 * 3600, 2) % 86400

    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = total_seconds % 60

    return f"{h:02d}-{m:02d}-{s:05.2f}"


def dec_to_nasa(dec):
    negative = dec < 0
    total_seconds = round(abs(dec) * 3600, 2)

    d = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = total_seconds % 60

    prefix = "M" if negative else ""
    return f"{prefix}{d:02d}-{m:02d}-{s:05.2f}"


# --------------------------------------------------
# 5. Wyszukiwarka: nazwa ALBO RA/Dec
# --------------------------------------------------

@app.get("/api/search")
def search_objects(
    name: str | None = Query(default=None, max_length=100),
    ra: float | None = Query(default=None, ge=0, lt=360),
    dec: float | None = Query(default=None, ge=-90, le=90),
    latitude: float = Query(default=50.3, ge=-90, le=90),
    longitude: float = Query(default=18.8, ge=-180, le=180),
    altitude_km: float = 0.3,
    radius: float = Query(default=1.0, gt=0, le=5),
    magnitude_limit: float = Query(default=20.0, ge=-5, le=25),
    observation_time: datetime | None = None
):
    try:
        # Wyszukiwanie po nazwie
        if name and name.strip():

            if ra is not None or dec is not None:
                raise HTTPException(
                    status_code=422,
                    detail="Podaj nazwe ALBO wspolrzedne RA/Dec"
                )

            details = get_asteroid_details(name.strip())

            return {
                "search_type": "name",
                "count": 1,
                "objects": [details]
            }

        # Wyszukiwanie po wspolrzednych
        if ra is None or dec is None:
            raise HTTPException(
                status_code=422,
                detail="Podaj nazwe lub oba parametry RA i Dec"
            )

        if observation_time is None:
            observation_time = datetime.now(timezone.utc)

        if observation_time.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="Czas musi zawierac strefe, np. Z"
            )

        result = get_asteroids(
            latitude=latitude,
            longitude=longitude,
            altitude_km=altitude_km,
            observation_time=observation_time,
            ra_center=ra_to_nasa(ra),
            dec_center=dec_to_nasa(dec),
            ra_half_width=radius,
            dec_half_width=radius,
            magnitude_limit=magnitude_limit
        )

        return {
            "search_type": "coordinates",
            "source": result["source"],
            "count": result["data"]["count"],
            "objects": result["data"]["objects"],
            "observation_time": result["data"]["observation_time"]
        }

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc)
        )

    except Exception as exc:
        print("SEARCH ERROR:", repr(exc))
        raise HTTPException(
            status_code=502,
            detail="Blad wyszukiwania danych NASA"
        )

app.include_router(catalog_router)