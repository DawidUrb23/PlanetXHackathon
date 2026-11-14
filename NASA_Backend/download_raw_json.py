import requests
import json

url = "https://ssd-api.jpl.nasa.gov/sb_ident.api"

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

response = requests.get(url, params=params, timeout=90)
response.raise_for_status()

data = response.json()

with open("nasa_asteroids_raw.json", "w", encoding="utf-8") as file:
    json.dump(data, file, indent=4, ensure_ascii=False)

print("Zapisano surowy JSON NASA!")
print("Adres zapytania:", response.url)
print("Pola główne:", list(data.keys()))