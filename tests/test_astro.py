import math
from datetime import datetime, timezone
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.astro_engine import AstroEngine
from app.main import app
from app.math_utils import azalt_to_cartesian_neu, get_camera_basis, project_gnomonic
from app.schemas import SkyRequest


@pytest.fixture(scope="session")
def client():
    """
    TestClient that triggers the FastAPI lifespan context manager.
    """
    with TestClient(app) as test_client:
        yield test_client


def test_sun_moon_known_positions(client):
    """
    Test 1: Check solar and lunar positions for a known date and observer location.
    Observer: Greenwich Observatory (Lat: 51.4769, Lon: 0.0, Elev: 45m).
    Date: Summer Solstice 2026-06-21 12:00:00 UTC.
    At local solar noon on summer solstice in Greenwich, the Sun should be due South (azimuth ~ 180 deg)
    and at its peak elevation (altitude ~ 62 deg).
    """
    from skyfield.api import wgs84
    engine: AstroEngine = app.state.astro_engine
    t = engine.ts.utc(2026, 6, 21, 12, 0, 0)
    obs = engine.earth + wgs84.latlon(51.4769, 0.0, elevation_m=45.0)
    
    # Sun
    sun_astro = obs.at(t).observe(engine.eph["sun"]).apparent()
    sun_alt, sun_az, sun_dist = sun_astro.altaz()
    
    # Verify Sun altitude is high summer (~ 61.9 deg) and azimuth is near 180 deg (South)
    assert 60.0 <= sun_alt.degrees <= 64.0, f"Sun altitude unexpected: {sun_alt.degrees}"
    assert 170.0 <= sun_az.degrees <= 190.0, f"Sun azimuth unexpected: {sun_az.degrees}"
    
    # Moon
    moon_astro = obs.at(t).observe(engine.eph["moon"]).apparent()
    moon_alt, moon_az, moon_dist = moon_astro.altaz()
    
    # Verify Moon distance is roughly between 350,000 km and 410,000 km
    moon_km = moon_dist.km
    assert 350000 <= moon_km <= 410000, f"Moon distance unexpected: {moon_km}"


def test_azimuth_wrap_around_north():
    """
    Test 2: Smooth transition across North (359 deg -> 1 deg).
    Ensure no discontinuities, NaNs, or coordinate inversion when looking near 0 / 360 deg.
    """
    # Camera pointing North at 0 deg azimuth, 45 deg altitude
    cam_az = 0.0
    cam_alt = 45.0
    
    # Two symmetric celestial objects:
    # Obj 1: just west of North at az = 359.0 deg (i.e. -1.0 deg)
    # Obj 2: just east of North at az = 1.0 deg (i.e. +1.0 deg)
    obj_azs = np.array([359.0, 1.0])
    obj_alts = np.array([45.0, 45.0])
    
    screen_x, screen_y, mask = project_gnomonic(
        az_deg=obj_azs,
        alt_deg=obj_alts,
        cam_az_deg=cam_az,
        cam_alt_deg=cam_alt,
        cam_roll_deg=0.0,
        fov_h_deg=60.0,
        fov_v_deg=40.0,
    )
    
    assert mask[0] and mask[1], "Both objects should be visible"
    # Obj 1 (359 deg) should be to the left (screen_x < 0)
    assert screen_x[0] < 0, f"Expected screen_x < 0, got {screen_x[0]}"
    # Obj 2 (1 deg) should be to the right (screen_x > 0)
    assert screen_x[1] > 0, f"Expected screen_x > 0, got {screen_x[1]}"
    
    # They should be perfectly symmetric around x = 0
    np.testing.assert_allclose(screen_x[0], -screen_x[1], atol=1e-5)
    np.testing.assert_allclose(screen_y[0], screen_y[1], atol=1e-5)
    
    # Test camera itself pointing across wrap boundary: cam_az = 359.5 deg
    screen_x_wrap, _, mask_wrap = project_gnomonic(
        az_deg=np.array([0.5]),
        alt_deg=np.array([45.0]),
        cam_az_deg=359.5,
        cam_alt_deg=45.0,
    )
    assert mask_wrap[0]
    # Object at 0.5 deg is 1.0 deg to the right of camera at 359.5 deg
    assert screen_x_wrap[0] > 0


def test_zenith_singularity_protection():
    """
    Test 3: Looking straight up into Zenith (altitude = 90 deg).
    Verify orthonormal basis remains valid (no NaN/Inf) and zenith object is centered.
    """
    cam_alt = 90.0
    cam_az = 180.0
    cam_roll = 0.0
    
    r, u, f = get_camera_basis(cam_az, cam_alt, cam_roll)
    
    # Basis vectors must be finite unit vectors
    assert not np.any(np.isnan(r))
    assert not np.any(np.isnan(u))
    assert not np.any(np.isnan(f))
    np.testing.assert_allclose(np.linalg.norm(r), 1.0, atol=1e-7)
    np.testing.assert_allclose(np.linalg.norm(u), 1.0, atol=1e-7)
    np.testing.assert_allclose(np.linalg.norm(f), 1.0, atol=1e-7)
    
    # Must be mutually perpendicular
    np.testing.assert_allclose(np.dot(r, u), 0.0, atol=1e-7)
    np.testing.assert_allclose(np.dot(r, f), 0.0, atol=1e-7)
    np.testing.assert_allclose(np.dot(u, f), 0.0, atol=1e-7)
    
    # Forward vector must point straight up
    np.testing.assert_allclose(f, [0.0, 0.0, 1.0], atol=1e-7)
    
    # Project an object located exactly at Zenith (alt = 90 deg)
    screen_x, screen_y, mask = project_gnomonic(
        az_deg=np.array([0.0]),
        alt_deg=np.array([90.0]),
        cam_az_deg=cam_az,
        cam_alt_deg=cam_alt,
        cam_roll_deg=cam_roll,
    )
    
    assert mask[0], "Zenith object must be visible when pointing at zenith"
    np.testing.assert_allclose(screen_x[0], 0.0, atol=1e-7)
    np.testing.assert_allclose(screen_y[0], 0.0, atol=1e-7)
    
    # Test roll at zenith
    r_rolled, u_rolled, f_rolled = get_camera_basis(cam_az, cam_alt, cam_roll_deg=45.0)
    np.testing.assert_allclose(np.linalg.norm(r_rolled), 1.0, atol=1e-7)
    np.testing.assert_allclose(f_rolled, [0.0, 0.0, 1.0], atol=1e-7)


def test_api_visible_endpoint(client):
    """
    Test 4: Integration test of POST /api/v1/sky/visible.
    """
    payload = {
        "latitude": 52.2297,
        "longitude": 21.0122,
        "elevation": 110.0,
        "timestamp": "2026-11-14T20:00:00Z",
        "azimuth": 180.0,
        "altitude": 45.0,
        "roll": 0.0,
        "fov_horizontal": 60.0,
        "fov_vertical": 40.0,
    }
    
    response = client.post("/api/v1/sky/visible", json=payload)
    assert response.status_code == 200, f"API error: {response.text}"
    
    data = response.json()
    assert "count" in data
    assert "objects" in data
    assert data["count"] == len(data["objects"])
    assert data["count"] > 0, "At least some stars/objects should be visible"
    
    # Validate object attributes and constraints
    types_found = set()
    for obj in data["objects"]:
        assert "id" in obj
        assert "name" in obj
        assert "type" in obj
        assert obj["type"] in ["planet", "star", "messier"]
        types_found.add(obj["type"])
        
        # Margin constraints: abs(screen) <= 1.2
        assert abs(obj["screen_x"]) <= 1.2 + 1e-4, f"screen_x out of bounds: {obj['screen_x']}"
        assert abs(obj["screen_y"]) <= 1.2 + 1e-4, f"screen_y out of bounds: {obj['screen_y']}"
        
        # Altitude filter constraint: alt >= -2.0
        assert obj["altitude"] >= -2.0 - 1e-4, f"altitude below -2.0: {obj['altitude']}"
        
        assert 0.0 <= obj["azimuth"] <= 360.0
        assert -90.0 <= obj["altitude"] <= 90.0

    assert "star" in types_found


def test_api_validation_errors(client):
    """
    Test input validation constraints (Pydantic range checking).
    """
    base_payload = {
        "latitude": 52.2297,
        "longitude": 21.0122,
        "elevation": 100.0,
        "timestamp": "2026-11-14T20:00:00Z",
        "azimuth": 180.0,
        "altitude": 45.0,
        "fov_horizontal": 60.0,
        "fov_vertical": 40.0,
    }
    
    # Invalid latitude > 90
    bad_lat = base_payload.copy()
    bad_lat["latitude"] = 95.0
    res = client.post("/api/v1/sky/visible", json=bad_lat)
    assert res.status_code == 422
    
    # Invalid azimuth > 360
    bad_az = base_payload.copy()
    bad_az["azimuth"] = 361.0
    res = client.post("/api/v1/sky/visible", json=bad_az)
    assert res.status_code == 422
    
    # Invalid FOV <= 0
    bad_fov = base_payload.copy()
    bad_fov["fov_horizontal"] = 0.0
    res = client.post("/api/v1/sky/visible", json=bad_fov)
    assert res.status_code == 422


def test_upload_and_healthy_endpoints(client):
    """
    Test 6: Integration test of /healthy and /upload for the Android client.
    """
    # Check /healthy
    health_res = client.get("/healthy")
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "healthy"

    # Android telemetry payload matching uploadPhotoToServer
    telemetry_payload = {
        "timestamp": "1731610800000",
        "latitude": 52.2297,
        "longitude": 21.0122,
        "gyroX": 0.01,
        "gyroY": -0.02,
        "gyroZ": 0.005,
        "accelX": 0.12,
        "accelY": 9.81,
        "accelZ": 0.35,
        "azimuth": 180.0,
        "pitch": 45.0,
        "roll": 0.0,
    }
    
    upload_res = client.post("/upload", json=telemetry_payload)
    assert upload_res.status_code == 200, f"Error: {upload_res.text}"
    
    data = upload_res.json()
    assert data["status"] == "success"
    assert "count" in data
    assert "objects" in data
    assert data["count"] == len(data["objects"])
    assert data["count"] > 0

