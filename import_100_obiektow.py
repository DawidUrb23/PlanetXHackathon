"""Jednorazowe utworzenie katalogu 100 wybranych, popularnych obiektow.

Uzycie:
    .\.venv\Scripts\python.exe import_100_obiektow.py
    .\.venv\Scripts\python.exe import_100_obiektow.py --enrich

--enrich: pobiera wspolrzedne obiektow Messiera/Caldwell z SIMBAD oraz
          probuje znalezc obrazek reprezentacyjny na oficjalnej stronie NASA.
          Siec moze byc niedostepna; brak wyniku pozostaje jako NULL.

Nie pobiera plikow JPG/FITS; przechowuje tylko odnosniki.
"""
import argparse
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import psycopg
import requests
from dotenv import load_dotenv

load_dotenv()

MESSIER_IDS = [
    1,2,3,4,5,7,8,9,10,11,12,13,14,15,16,17,19,20,22,24,27,28,30,
    31,32,33,35,42,43,44,45,46,48,49,51,53,54,55,56,57,58,59,60,61,
    62,63,64,65,66,67,68,69,70,71,72,74,75,76,77,78,79,80,81,82,83,
    84,85,86,87,88,89,90,91,92,94,95,96,98,99,100,101,102,104,105,
    106,107,108,109,110
]
assert len(MESSIER_IDS) == 89

HUBBLE = 'https://science.nasa.gov/mission/hubble/science/explore-the-night-sky'
SOLAR = [
    ('mercury','Merkury','planet','https://science.nasa.gov/mercury/facts/'),
    ('venus','Wenus','planet','https://science.nasa.gov/venus/facts/'),
    ('mars','Mars','planet','https://science.nasa.gov/mars/facts/'),
    ('jupiter','Jowisz','planet','https://science.nasa.gov/jupiter/facts/'),
    ('saturn','Saturn','planet','https://science.nasa.gov/saturn/facts/'),
    ('uranus','Uran','planet','https://science.nasa.gov/uranus/facts/'),
    ('neptune','Neptun','planet','https://science.nasa.gov/neptune/facts/'),
    ('sun','Slonce','star','https://science.nasa.gov/sun/facts/'),
    ('moon','Ksiezyc','moon','https://science.nasa.gov/moon/facts/'),
    ('pluto','Pluton','dwarf_planet','https://science.nasa.gov/dwarf-planets/pluto/facts/'),
]
# Siedem planet widocznych z Ziemi + Slonce + Ksiezyc + Pluton (planeta karlowata).
# Ziemia nie jest znacznikiem na niebie dla obserwatora stojacego na Ziemi.

KNOWN = {
    1:'Mglawica Krab', 8:'Mglawica Laguna', 13:'Gromada Herkulesa',
    16:'Mglawica Orzel', 17:'Mglawica Omega', 20:'Mglawica Trojdzielna',
    27:'Mglawica Hantle', 31:'Galaktyka Andromedy', 33:'Galaktyka Trojkata',
    42:'Mglawica Oriona', 44:'Zlobek', 45:'Plejady', 51:'Galaktyka Wir',
    57:'Mglawica Pierscien', 63:'Galaktyka Slonecznik', 64:'Galaktyka Czarne Oko',
    81:'Galaktyka Bodego', 82:'Galaktyka Cygaro', 87:'Galaktyka M87',
    101:'Galaktyka Wiatraczek', 104:'Galaktyka Sombrero'
}

OBJECTS = [
    dict(key=k, name=n, designation=k.title(), object_type=t, moving=True,
         source_url=url, simbad_name=None)
    for k,n,t,url in SOLAR
]
OBJECTS += [
    dict(key=f'm{n}', name=KNOWN.get(n, f'Messier {n}'), designation=f'M{n}',
         object_type='deep_sky', moving=False,
         source_url=f'{HUBBLE}/hubble-messier-catalog/messier-{n}/',
         simbad_name=f'M {n}')
    for n in MESSIER_IDS
]
OBJECTS.append(dict(key='c11',name='Mglawica Banka',designation='Caldwell 11',
                    object_type='nebula',moving=False,
                    source_url=f'{HUBBLE}/hubble-caldwell-catalog/caldwell-11/',
                    simbad_name='NGC 7635'))
assert len(OBJECTS) == 100

SCHEMA = '''
CREATE TABLE IF NOT EXISTS featured_sky_objects (
  object_key VARCHAR(32) PRIMARY KEY,
  name VARCHAR(160) NOT NULL,
  designation VARCHAR(80) NOT NULL,
  object_type VARCHAR(40) NOT NULL,
  is_moving BOOLEAN NOT NULL DEFAULT FALSE,
  ra_deg DOUBLE PRECISION,
  dec_deg DOUBLE PRECISION,
  image_url TEXT,
  image_source_url TEXT NOT NULL,
  image_verified BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (ra_deg IS NULL OR (ra_deg >= 0 AND ra_deg < 360)),
  CHECK (dec_deg IS NULL OR (dec_deg >= -90 AND dec_deg <= 90))
);
'''

def conn():
    return psycopg.connect(
        host=os.getenv('DB_HOST','localhost'),
        port=os.getenv('DB_PORT','5432'),
        dbname=os.getenv('DB_NAME','nasa_spaceapps'),
        user=os.getenv('DB_USER','postgres'),
        password=os.getenv('DB_PASSWORD'),
        connect_timeout=10,
    )

def seed():
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(SCHEMA)
            for item in OBJECTS:
                cur.execute('''
                INSERT INTO featured_sky_objects
                  (object_key,name,designation,object_type,is_moving,image_source_url)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (object_key) DO UPDATE SET
                  name=EXCLUDED.name,
                  designation=EXCLUDED.designation,
                  object_type=EXCLUDED.object_type,
                  is_moving=EXCLUDED.is_moving,
                  image_source_url=EXCLUDED.image_source_url
                ''', (item['key'],item['name'],item['designation'],
                      item['object_type'],item['moving'],item['source_url']))
        c.commit()
    print('Katalog 100 obiektow zapisany w PostgreSQL.')

def resolve_positions():
    try:
        from astroquery.simbad import Simbad
    except ImportError:
        print('Brak astroquery: pip install astroquery')
        return
    targets = [o for o in OBJECTS if not o['moving']]
    simbad = Simbad()
    updates=[]
    # Jedno zapytanie SIMBAD na 20 nazw; nie 90 zapytan HTTP.
    for offset in range(0,len(targets),20):
        batch=targets[offset:offset+20]
        try:
            table=simbad.query_objects([o['simbad_name'] for o in batch])
            if table is None: continue
            found={}
            for row in table:
                match=re.sub(r'\s+', '', str(row['matched_id'])).upper()
                found[match]=(float(row['ra']),float(row['dec']))
            for ob in batch:
                match=re.sub(r'\s+', '', ob['simbad_name']).upper()
                if match in found:
                    ra,dec=found[match]
                    updates.append((ra,dec,ob['key']))
            print(f'SIMBAD: {min(offset+20,len(targets))}/{len(targets)} nazw, znaleziono {len(updates)} pozycji')
        except Exception as exc:
            print('SIMBAD blad dla partii',offset,repr(exc))
    if updates:
        with conn() as c:
            with c.cursor() as cur:
                cur.executemany('''UPDATE featured_sky_objects SET ra_deg=%s,dec_deg=%s,updated_at=NOW()
                                   WHERE object_key=%s AND is_moving=FALSE''',updates)
            c.commit()
    print('Pozycje stale uzupelnione:',len(updates))

def image_from_nasa_page(item):
    try:
        resp=requests.get(item['source_url'],timeout=12,
                          headers={'User-Agent':'PlanetXHackathon/1.0 educational project'})
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(resp.text,'html.parser')
        tag=soup.find('meta',attrs={'property':'og:image'})
        url=tag.get('content') if tag else None
        if url and url.startswith('https://') and urlparse(url).hostname in {
            'science.nasa.gov','assets.science.nasa.gov','images-assets.nasa.gov',
            'www.nasa.gov','images.nasa.gov'
        }:
            # To obraz reprezentacyjny strony. Moze wymagac kontroli redakcyjnej.
            return (url,item['key'])
    except Exception as exc:
        print(f"NASA obraz {item['key']}: {str(exc)[:90]}")
    return None

def enrich_images():
    updates=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(image_from_nasa_page,o) for o in OBJECTS]
        for i,f in enumerate(as_completed(futures),1):
            res=f.result()
            if res: updates.append(res)
            if i % 20 == 0: print(f'Strony NASA: {i}/100, znalezione adresy: {len(updates)}')
    if updates:
        with conn() as c:
            with c.cursor() as cur:
                cur.executemany('''UPDATE featured_sky_objects SET image_url=%s,
                    image_verified=FALSE,updated_at=NOW() WHERE object_key=%s''',updates)
            c.commit()
    print('Wstepne adresy ilustracji NASA:',len(updates),
          '(image_verified=FALSE az do recznej weryfikacji)')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--enrich',action='store_true',help='Pobierz pozycje i linki do fotografii')
    args=parser.parse_args()
    seed()
    if args.enrich:
        resolve_positions()
        enrich_images()
    with conn() as c:
        with c.cursor() as cur:
            cur.execute('''SELECT COUNT(*),COUNT(ra_deg),COUNT(image_url)
                           FROM featured_sky_objects''')
            total,positions,images=cur.fetchone()
    print(f'W BAZIE: razem={total}, pozycje={positions}, adresy_ilustracji={images}')
