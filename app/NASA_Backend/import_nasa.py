
import os
import requests
import psycopg

from dotenv import load_dotenv

load_dotenv()

# 1. Pobieranie danych z NASA
url = "https://ssd-api.jpl.nasa.gov/sbdb.api"

response = requests.get(
    url,
    params={"sstr": "Bennu", "phys-par": "1"},
    timeout=30
)
response.raise_for_status()

data = response.json()
obj = data["object"]

name = obj["fullname"].strip()
identifier = str(obj["spkid"])

print("Pobrano z NASA:", name)

# 2. Połączenie z PostgreSQL
with psycopg.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
) as conn:

    with conn.cursor() as cur:

        # Zapis źródła danych
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
                    "JPL Small-Body Database",
                    "NASA JPL",
                    url
                )
            )
            source_id = cur.fetchone()[0]

        # Sprawdzenie, czy Bennu już istnieje
        cur.execute(
            """
            SELECT id
            FROM celestial_objects
            WHERE nasa_identifier = %s
            LIMIT 1
            """,
            (identifier,)
        )

        result = cur.fetchone()

        if result:
            cur.execute(
                """
                UPDATE celestial_objects
                SET name = %s,
                    object_type = %s
                WHERE id = %s
                """,
                (name, "asteroid", result[0])
            )
            object_id = result[0]
        else:
            cur.execute(
                """
                INSERT INTO celestial_objects
                    (name, object_type, nasa_identifier)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (name, "asteroid", identifier)
            )
            object_id = cur.fetchone()[0]

    conn.commit()

print("Zapisano obiekt w PostgreSQL!")
print("ID obiektu:", object_id)
print("ID źródła:", source_id)
