
import os
import requests
import psycopg
from dotenv import load_dotenv

load_dotenv()

# Wyszukiwanie zdjęć Bennu w NASA
url = "https://images-api.nasa.gov/search"

response = requests.get(
    url,
    params={
        "q": "asteroid Bennu",
        "media_type": "image",
        "page_size": 20
    },
    timeout=30
)

response.raise_for_status()
data = response.json()

items = data.get("collection", {}).get("items", [])

print("Znaleziono wyników na stronie:", len(items))

with psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
) as conn:

    with conn.cursor() as cur:

        # Szukamy Bennu w naszej bazie
        cur.execute(
            """
            SELECT id
            FROM celestial_objects
            WHERE nasa_identifier = %s
            """,
            ("20101955",)
        )

        result = cur.fetchone()

        if not result:
            raise ValueError(
                "Nie znaleziono Bennu w celestial_objects"
            )

        object_id = result[0]

        # Dodajemy źródło NASA Images
        cur.execute(
            """
            SELECT id
            FROM data_sources
            WHERE source_url = %s
            LIMIT 1
            """,
            (url,)
        )

        result = cur.fetchone()

        if result:
            source_id = result[0]
        else:
            cur.execute(
                """
                INSERT INTO data_sources
                    (name, provider, source_url)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    "NASA Image and Video Library",
                    "NASA",
                    url
                )
            )
            source_id = cur.fetchone()[0]

        count = 0

        for item in items:
            metadata = item.get("data", [{}])[0]
            links = item.get("links", [])

            image_link = next(
                (
                    link.get("href")
                    for link in links
                    if link.get("render") == "image"
                    and link.get("href")
                ),
                None
            )

            if not image_link:
                continue

            title = metadata.get("title", "Bennu")
            description = metadata.get("description", "")

            # Nie zapisujemy tego samego URL dwa razy
            cur.execute(
                """
                SELECT id
                FROM images
                WHERE object_id = %s
                  AND image_url = %s
                """,
                (object_id, image_link)
            )

            if cur.fetchone():
                continue

            cur.execute(
                """
                INSERT INTO images
                    (object_id, source_id, title,
                     image_url, description)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    object_id,
                    source_id,
                    title,
                    image_link,
                    description
                )
            )

            count += 1

    conn.commit()

print("Dodano zdjęć do bazy:", count)
