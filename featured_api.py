"""Router 100 stalych kart obiektow z orientacja na niebie (AR).
W api.py: from featured_api import router as featured_router
           app.include_router(featured_router)
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from nasa_asteroid_service import db_connection

router = APIRouter(prefix='/api/catalog', tags=['Featured sky'])

@router.get('/featured')
def featured_objects(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    alt_m: float = Query(0.0, ge=-500, le=10000),
):
    """100 zapisanych kart; Alt/Az liczone dla miejsca i aktualnego czasu.
    Brak pozycji -> null (nie wyswietlaj znacznika AR).
    """
    try:
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute('''SELECT object_key,name,designation,object_type,is_moving,
                               ra_deg,dec_deg,image_url,image_source_url,image_verified
                               FROM featured_sky_objects ORDER BY object_key''')
                items = cur.fetchall()
    except Exception as exc:
        print('FEATURED DATABASE ERROR:', repr(exc))
        raise HTTPException(status_code=500, detail='Blad odczytu katalogu')

    from astropy.coordinates import SkyCoord, EarthLocation, AltAz, get_body
    from astropy.time import Time
    from astropy.utils import iers
    import astropy.units as u

    iers.conf.auto_download = False  # zadna dodatkowa blokujaca operacja sieciowa
    when = datetime.now(timezone.utc)
    obs_time = Time(when)
    location = EarthLocation(lat=lat*u.deg, lon=lon*u.deg, height=alt_m*u.m)
    horizontal = AltAz(obstime=obs_time, location=location)
    solar_names = {'mercury','venus','mars','jupiter','saturn','uranus',
                   'neptune','sun','moon'}

    output=[]
    for item in items:
        item=dict(item)
        az=alt=None
        try:
            if item['is_moving'] and item['object_key'] in solar_names:
                # Geocentryczne i topocentryczne pozycje ruchomych cial;
                # astropy builtin - nie ephemerydy JPL Horizons.
                coord=get_body(item['object_key'], obs_time, location)
            elif not item['is_moving'] and item['ra_deg'] is not None and item['dec_deg'] is not None:
                coord=SkyCoord(ra=item['ra_deg']*u.deg,dec=item['dec_deg']*u.deg,frame='icrs')
            else:
                coord=None
            if coord is not None:
                transformed=coord.transform_to(horizontal)
                az=round(float(transformed.az.deg),5)
                alt=round(float(transformed.alt.deg),5)
        except Exception as exc:
            print('POSITION ERROR:', item['object_key'], repr(exc))
        output.append({
            'id':item['object_key'],'name':item['name'],
            'designation':item['designation'],'object_type':item['object_type'],
            'moving':item['is_moving'],
            'ra':item['ra_deg'] if not item['is_moving'] else None,
            'dec':item['dec_deg'] if not item['is_moving'] else None,
            'azimuth':az,'altitude':alt,
            'visible_above_horizon':(alt>=0 if alt is not None else None),
            'image_url':item['image_url'],
            'image_source_url':item['image_source_url'],
            'image_verified':item['image_verified'],
        })

    return {'source':'postgresql+astropy','observation_time':when.isoformat(),
            'observer':{'lat':lat,'lon':lon,'alt_m':alt_m},
            'count':len(output), 'objects':output,
            'note':'Pozycje planet z Astropy, Pluto bez pozycji. Obrazy wymagaja weryfikacji.'}
