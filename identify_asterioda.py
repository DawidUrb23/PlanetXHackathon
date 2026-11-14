
import requests

URL = "https://ssd-api.jpl.nasa.gov/sb_ident.api"

# Przykładowa lokalizacja obserwatora i obszar nieba.
# To test API, a nie odczyt z telefonu.
params = {
    "lat": 50.3,
    "lon": 18.8,
    "alt": 0.3,
    "obs-time": "2026-11-14_20:00:00",
    "fov-ra-center": "03-00-00",
    "fov-dec-center": "20-00-00",
    "fov-ra-hwidth": 2,
    "fov-dec-hwidth": 2,
    "two-pass": "true",
    "suppress-first-pass": "true",
    "req-elem": "false",
    "vmag-lim": 22
}

print("Wysyłam zapytanie do NASA JPL...")

response = requests.get(
    URL,
    params=params,
    headers={
        "User-Agent": "SpaceAppsSkyExplorer/0.1 (student project)"
    },
    timeout=90
)
response.raise_for_status()

data = response.json()

if "error" in data:
    raise RuntimeError(data["error"])

fields = data.get("fields_second", [])
objects = data.get("data_second_pass", [])

print("Znaleziono asteroid:", len(objects))
print("Kolumny:", fields)

for obj in objects[:20]:
    for field, value in zip(fields, obj):
        print(f"{field}: {value}")
    print("--------------------")
