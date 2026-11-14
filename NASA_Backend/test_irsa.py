
import requests

url = "https://irsa.ipac.caltech.edu/TAP/sync"

query = """
SELECT TOP 1
    a.uri,
    p.time_bounds_lower
FROM spherex.artifact a
JOIN spherex.plane p
    ON a.planeid = p.planeid
"""

params = {
    "REQUEST": "doQuery",
    "LANG": "ADQL",
    "FORMAT": "votable",
    "QUERY": query
}

try:
    print("Sprawdzam odpowiedz NASA IRSA...")

    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    print("STATUS HTTP:", response.status_code)
    print(
        "CONTENT TYPE:",
        response.headers.get("Content-Type")
    )

    print("\nPOCZATEK ODPOWIEDZI:")
    print(response.text[:2000])

except requests.exceptions.Timeout:
    print("BLAD: NASA IRSA nie odpowiedziala w 30 sekund.")

except requests.exceptions.RequestException as error:
    print("BLAD POLACZENIA:", repr(error))
