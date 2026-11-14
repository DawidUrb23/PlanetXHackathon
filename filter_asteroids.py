
import json

with open("nasa_asteroids_raw.json", encoding="utf-8") as f:
    data = json.load(f)

fields = data["fields_second"]
rows = data["data_second_pass"]

objects = []

for row in rows:
    asteroid = dict(zip(fields, row))

    distance_arcsec = float(
        asteroid["Dist. from center Norm (\")"]
    )

    # Tylko obiekty w odległości do 1 stopnia
    if distance_arcsec > 3600:
        continue

    objects.append({
        "name": asteroid["Object name"],
        "ra": asteroid["Astrometric RA (hh:mm:ss)"],
        "dec": asteroid["Astrometric Dec (dd mm'ss\")"],
        "magnitude": (
            asteroid["Visual magnitude (V)"]
        ),
        "distance_from_center_deg": round(
            distance_arcsec / 3600, 4
        )
    })

objects.sort(
    key=lambda x: x["distance_from_center_deg"]
)

result = {
    "object_type": "asteroid",
    "count": len(objects),
    "objects": objects
}

with open("asteroids_filtered.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=4, ensure_ascii=False)

print("Wszystkich rekordów:", len(rows))
print("Wybranych asteroid:", len(objects))

for obj in objects[:10]:
    print(obj)
