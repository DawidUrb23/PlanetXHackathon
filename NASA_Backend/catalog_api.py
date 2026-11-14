
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from nasa_asteroid_service import db_connection


router = APIRouter(prefix="/api/catalog", tags=["Catalog"])


def like_pattern(term):
    escaped = (
        term.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
    )
    return f"%{escaped}%"


def format_object(row, images=None):
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "designation": row["designation"] or "",
        "object_type": row["object_type"],
        "description": row["description"] or "Brak opisu.",
        "ra": row["ra"],
        "dec": row["dec"],
        "sep_deg": round(row["sep_deg"], 4)
        if row.get("sep_deg") is not None else None,
        "magnitude": None,
        "images": images or []
    }



@router.get("/objects")
def search_catalog(
    ra: float | None = Query(None, ge=0, lt=360),
    dec: float | None = Query(None, ge=-90, le=90),
    radius: float = Query(1.0, gt=0, le=30),
    query: str | None = None,
    search: str | None = None,
    name: str | None = None,
    limit: int = Query(100, ge=1, le=500)
):
    if (ra is None) != (dec is None):
        raise HTTPException(
            status_code=422,
            detail="Podaj jednoczesnie RA i Dec."
        )

    search_text = query or search or name

    # Wyszukujemy obiekty zapisane w PostgreSQL.
    # RA/Dec pochodza z tabeli observations.
    sql = """
        WITH base AS (
            SELECT
                o.id,
                o.name,
                o.nasa_identifier AS designation,
                o.object_type,
                o.description,
                MIN(obs.ra) AS ra,
                MIN(obs.dec) AS dec
            FROM celestial_objects o
            LEFT JOIN observations obs
                ON obs.object_id = o.id
            GROUP BY
                o.id,
                o.name,
                o.nasa_identifier,
                o.object_type,
                o.description
        )
    """

    params = []

    if ra is not None:
        separation = """
            degrees(acos(least(1.0, greatest(-1.0,
                sin(radians(base.dec)) * sin(radians(%s))
                + cos(radians(base.dec)) * cos(radians(%s))
                * cos(radians(base.ra - %s))
            ))))
        """
        params.extend([dec, dec, ra])
    else:
        separation = "NULL::double precision"

    sql += f"""
        SELECT q.*
        FROM (
            SELECT
                base.*,
                {separation} AS sep_deg
            FROM base
        ) q
    """

    filters = []

    if ra is not None:
        filters.append("q.sep_deg <= %s")
        params.append(radius)

    if search_text and search_text.strip():
        for term in search_text.strip().split():
            filters.append("""
                (
                    q.name ILIKE %s
                    OR q.designation ILIKE %s
                    OR q.description ILIKE %s
                    OR q.object_type ILIKE %s
                )
            """)
            params.extend([like_pattern(term)] * 4)

    if filters:
        sql += " WHERE " + " AND ".join(filters)

    if ra is not None:
        sql += " ORDER BY q.sep_deg, q.id"
    else:
        sql += " ORDER BY q.name, q.id"

    sql += " LIMIT %s"
    params.append(limit)

    try:
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

                results = []

                for row in rows:
                    cur.execute(
                        """
                        SELECT title, image_url
                        FROM images
                        WHERE object_id = %s
                        ORDER BY title
                        LIMIT 10
                        """,
                        (row["id"],)
                    )

                    images = [
                        {
                            "title": img["title"],
                            "url": img["image_url"]
                        }
                        for img in cur.fetchall()
                    ]

                    results.append(
                        format_object(row, images)
                    )

        return {
            "count": len(results),
            "asteroids": results
        }

    except Exception as exc:
        print("CATALOG SEARCH ERROR:", repr(exc))
        raise HTTPException(
            status_code=502,
            detail="Blad wyszukiwania w bazie danych."
        )


@router.get("/objects/details")
def catalog_details(
    name: str = Query(..., min_length=1, max_length=100)
):
    try:
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        o.id,
                        o.name,
                        o.nasa_identifier AS designation,
                        o.object_type,
                        o.description,
                        MIN(obs.ra) AS ra,
                        MIN(obs.dec) AS dec
                    FROM celestial_objects o
                    LEFT JOIN observations obs
                        ON obs.object_id = o.id
                    WHERE
                        o.name ILIKE %s
                        OR o.nasa_identifier ILIKE %s
                    GROUP BY
                        o.id,
                        o.name,
                        o.nasa_identifier,
                        o.object_type,
                        o.description
                    ORDER BY o.id
                    LIMIT 1
                    """,
                    (
                        like_pattern(name.strip()),
                        like_pattern(name.strip())
                    )
                )

                obj = cur.fetchone()

                if obj is None:
                    raise HTTPException(
                        status_code=404,
                        detail="Nie znaleziono obiektu."
                    )

                cur.execute(
                    """
                    SELECT title, image_url
                    FROM images
                    WHERE object_id = %s
                    ORDER BY title
                    LIMIT 50
                    """,
                    (obj["id"],)
                )

                images = [
                    {
                        "title": row["title"],
                        "url": row["image_url"]
                    }
                    for row in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT
                        wavelength_band,
                        data_url,
                        observed_at
                    FROM observations
                    WHERE object_id = %s
                    ORDER BY observed_at DESC NULLS LAST
                    LIMIT 50
                    """,
                    (obj["id"],)
                )

                observations = [
                    {
                        "wavelength_band": row["wavelength_band"],
                        "data_url": row["data_url"],
                        "observed_at": (
                            row["observed_at"].isoformat()
                            if row["observed_at"] else None
                        )
                    }
                    for row in cur.fetchall()
                ]

        return {
            "id": str(obj["id"]),
            "name": obj["name"],
            "designation": obj["designation"],
            "object_type": obj["object_type"],
            "description": obj["description"] or "Brak opisu.",
            "ra": obj["ra"],
            "dec": obj["dec"],
            "images": images,
            "observations": observations
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("CATALOG DETAILS ERROR:", repr(exc))
        raise HTTPException(
            status_code=502,
            detail="Blad odczytu szczegolow z bazy."
        )
