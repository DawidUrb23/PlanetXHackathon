import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from skyfield.api import Loader, Star, wgs84
from skyfield.magnitudelib import planetary_magnitude

from app.math_utils import project_gnomonic
from app.schemas import AstroObject, SkyRequest

logger = logging.getLogger("astro_engine")

PROMINENT_STAR_NAMES: Dict[int, str] = {
    32349: "Sirius",
    30438: "Canopus",
    69673: "Arcturus",
    71683: "Alpha Centauri A",
    71681: "Alpha Centauri B",
    91262: "Vega",
    24608: "Capella",
    24436: "Rigel",
    37279: "Procyon",
    7588: "Achernar",
    27989: "Betelgeuse",
    68702: "Hadar",
    97649: "Altair",
    60718: "Acrux",
    21421: "Aldebaran",
    65474: "Spica",
    80763: "Antares",
    37826: "Pollux",
    113963: "Fomalhaut",
    102098: "Deneb",
    61084: "Mimosa",
    49669: "Regulus",
    31681: "Adhara",
    36850: "Castor",
    62434: "Gacrux",
    25336: "Bellatrix",
    26311: "Elnath",
    45238: "Miaplacidus",
    25428: "Alnilam",
    109268: "Alnair",
    65378: "Alioth",
    11767: "Polaris",
    95947: "Albireo",
    54061: "Merak",
    53910: "Dubhe",
    67301: "Alkaid",
    14576: "Algol",
    72607: "Kochab",
    82273: "Rasalhague",
    86032: "Shaula",
    85927: "Kaus Australis",
    107315: "Enif",
    113368: "Markab",
    84345: "Peacock",
    39953: "Naos",
    10826: "Mirfak",
    25930: "Alnitak",
    26727: "Saiph",
    25204: "Mintaka",
    68756: "Muhlifain",
    92855: "Sulafat",
    92420: "Sheliak",
}

# Approximate visual magnitudes for notable Messier objects
MESSIER_MAGNITUDES: Dict[str, float] = {
    "M31": 3.44,
    "M42": 4.0,
    "M45": 1.6,
    "M44": 3.7,
    "M7": 3.3,
    "M6": 4.2,
    "M8": 6.0,
    "M13": 5.8,
    "M22": 5.1,
    "M24": 4.6,
    "M25": 4.6,
    "M33": 5.7,
    "M35": 5.3,
    "M41": 4.5,
    "M47": 4.2,
}


class AstroEngine:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        loader = Loader(str(data_dir))
        self.ts = loader.timescale()
        
        # 1. Ephemeris & Solar System
        eph_path = data_dir / "de421.bsp"
        if not eph_path.exists():
            raise FileNotFoundError(f"Missing ephemeris file: {eph_path}. Run setup_data.py first.")
        self.eph = loader("de421.bsp")
        self.earth = self.eph["earth"]
        
        self.planets = [
            ("sun", "Sun", self.eph["sun"], -26.74),
            ("moon", "Moon", self.eph["moon"], -12.74),
            ("mercury", "Mercury", self.eph["mercury"], None),
            ("venus", "Venus", self.eph["venus"], None),
            ("mars", "Mars", self.eph["mars"], None),
            ("jupiter", "Jupiter", self.eph["jupiter barycenter"], None),
            ("saturn", "Saturn", self.eph["saturn barycenter"], None),
            ("uranus", "Uranus", self.eph["uranus barycenter"], None),
            ("neptune", "Neptune", self.eph["neptune barycenter"], None),
            ("pluto", "Pluto", self.eph["pluto barycenter"], 15.1),
        ]
        
        # 2. Hipparcos bright stars catalog
        stars_path = data_dir / "stars_bright.csv"
        if not stars_path.exists():
            raise FileNotFoundError(f"Missing stars file: {stars_path}. Run setup_data.py first.")
        
        df_stars = pd.read_csv(stars_path, index_col="hip")
        # Ensure clean coordinates
        df_stars = df_stars.dropna(subset=["ra_degrees", "dec_degrees"])
        df_stars["parallax_mas"] = df_stars["parallax_mas"].fillna(0.0)
        df_stars["ra_mas_per_year"] = df_stars["ra_mas_per_year"].fillna(0.0)
        df_stars["dec_mas_per_year"] = df_stars["dec_mas_per_year"].fillna(0.0)
        
        self.stars_hip_ids = [int(hip) for hip in df_stars.index]
        self.stars_names = [PROMINENT_STAR_NAMES.get(hip, f"HIP {hip}") for hip in self.stars_hip_ids]
        self.stars_mags = df_stars["magnitude"].astype(float).to_numpy()
        self.stars_object = Star.from_dataframe(df_stars)
        logger.info(f"Loaded {len(self.stars_hip_ids)} stars into vectorized Star object")
        
        # 3. Messier objects catalog
        messier_path = data_dir / "messier.json"
        if not messier_path.exists():
            raise FileNotFoundError(f"Missing messier file: {messier_path}. Run setup_data.py first.")
        
        with open(messier_path, "r", encoding="utf-8") as f:
            messier_items = json.load(f)
            
        self.messier_ids = [m["id"] for m in messier_items]
        self.messier_names = [m["name"] for m in messier_items]
        self.messier_mags = [MESSIER_MAGNITUDES.get(m["id"]) for m in messier_items]
        
        ra_hours = np.array([m["ra_hours"] for m in messier_items], dtype=np.float64)
        dec_deg = np.array([m["dec_degrees"] for m in messier_items], dtype=np.float64)
        self.messier_object = Star(ra_hours=ra_hours, dec_degrees=dec_deg)
        logger.info(f"Loaded {len(self.messier_ids)} Messier objects into vectorized Star object")

    def get_solar_system_positions(self, observer, t) -> Tuple[List[dict], np.ndarray, np.ndarray]:
        """
        Compute positions and magnitudes for Solar System bodies.
        """
        bodies_info = []
        alt_list = []
        az_list = []
        
        for p_id, p_name, target, fixed_mag in self.planets:
            astrometric = observer.at(t).observe(target)
            alt, az, _ = astrometric.apparent().altaz()
            
            mag = fixed_mag
            if mag is None:
                try:
                    mag = float(planetary_magnitude(astrometric))
                except Exception:
                    mag = None
            
            bodies_info.append({
                "id": p_id,
                "name": p_name,
                "type": "planet",
                "magnitude": round(mag, 2) if mag is not None else None,
            })
            alt_list.append(alt.degrees)
            az_list.append(az.degrees)
            
        return bodies_info, np.array(alt_list, dtype=np.float64), np.array(az_list, dtype=np.float64)

    def compute_visible(self, req: SkyRequest) -> List[AstroObject]:
        """
        Compute all astronomical objects visible in the camera FOV given the request parameters.
        Zero disk or network operations occur here.
        """
        t = self.ts.from_datetime(req.timestamp)
        observer = self.earth + wgs84.latlon(
            latitude_degrees=req.latitude,
            longitude_degrees=req.longitude,
            elevation_m=req.elevation,
        )
        
        visible_objects: List[AstroObject] = []
        
        # 1. Solar system bodies
        planets_info, planet_alts, planet_azs = self.get_solar_system_positions(observer, t)
        p_screen_x, p_screen_y, p_mask = project_gnomonic(
            az_deg=planet_azs,
            alt_deg=planet_alts,
            cam_az_deg=req.azimuth,
            cam_alt_deg=req.altitude,
            cam_roll_deg=req.roll,
            fov_h_deg=req.fov_horizontal,
            fov_v_deg=req.fov_vertical,
            margin=1.2,
            min_alt_deg=-2.0,
        )
        
        for idx in np.where(p_mask)[0]:
            p = planets_info[idx]
            visible_objects.append(
                AstroObject(
                    id=p["id"],
                    name=p["name"],
                    type="planet",
                    magnitude=p["magnitude"],
                    azimuth=round(float(planet_azs[idx]), 3),
                    altitude=round(float(planet_alts[idx]), 3),
                    screen_x=round(float(p_screen_x[idx]), 4),
                    screen_y=round(float(p_screen_y[idx]), 4),
                )
            )
            
        # 2. Vectorized Hipparcos stars
        astrometric_stars = observer.at(t).observe(self.stars_object)
        alt_stars, az_stars, _ = astrometric_stars.apparent().altaz()
        alt_s_deg = alt_stars.degrees
        az_s_deg = az_stars.degrees
        
        s_screen_x, s_screen_y, s_mask = project_gnomonic(
            az_deg=az_s_deg,
            alt_deg=alt_s_deg,
            cam_az_deg=req.azimuth,
            cam_alt_deg=req.altitude,
            cam_roll_deg=req.roll,
            fov_h_deg=req.fov_horizontal,
            fov_v_deg=req.fov_vertical,
            margin=1.2,
            min_alt_deg=-2.0,
        )
        
        for idx in np.where(s_mask)[0]:
            hip = self.stars_hip_ids[idx]
            visible_objects.append(
                AstroObject(
                    id=f"hip_{hip}",
                    name=self.stars_names[idx],
                    type="star",
                    magnitude=round(float(self.stars_mags[idx]), 2),
                    azimuth=round(float(az_s_deg[idx]), 3),
                    altitude=round(float(alt_s_deg[idx]), 3),
                    screen_x=round(float(s_screen_x[idx]), 4),
                    screen_y=round(float(s_screen_y[idx]), 4),
                )
            )
            
        # 3. Vectorized Messier objects
        astrometric_messier = observer.at(t).observe(self.messier_object)
        alt_messier, az_messier, _ = astrometric_messier.apparent().altaz()
        alt_m_deg = alt_messier.degrees
        az_m_deg = az_messier.degrees
        
        m_screen_x, m_screen_y, m_mask = project_gnomonic(
            az_deg=az_m_deg,
            alt_deg=alt_m_deg,
            cam_az_deg=req.azimuth,
            cam_alt_deg=req.altitude,
            cam_roll_deg=req.roll,
            fov_h_deg=req.fov_horizontal,
            fov_v_deg=req.fov_vertical,
            margin=1.2,
            min_alt_deg=-2.0,
        )
        
        for idx in np.where(m_mask)[0]:
            mag = self.messier_mags[idx]
            visible_objects.append(
                AstroObject(
                    id=self.messier_ids[idx],
                    name=self.messier_names[idx],
                    type="messier",
                    magnitude=round(float(mag), 2) if mag is not None else None,
                    azimuth=round(float(az_m_deg[idx]), 3),
                    altitude=round(float(alt_m_deg[idx]), 3),
                    screen_x=round(float(m_screen_x[idx]), 4),
                    screen_y=round(float(m_screen_y[idx]), 4),
                )
            )
            
        return visible_objects
