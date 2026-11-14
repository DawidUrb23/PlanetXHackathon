import numpy as np
from typing import Tuple


def azalt_to_cartesian_neu(az_deg: np.ndarray, alt_deg: np.ndarray) -> np.ndarray:
    """
    Convert horizontal coordinates (Azimuth, Altitude) to local Cartesian unit vectors (North, East, Up).
    
    Coordinate conventions:
    - Azimuth (A): 0 deg = North, 90 deg = East, 180 deg = South, 270 deg = West.
    - Altitude (h): -90 deg (Nadir) to +90 deg (Zenith).
    
    Formula:
    - N = cos(h) * cos(A)
    - E = cos(h) * sin(A)
    - Up = sin(h)
    
    Returns:
        np.ndarray of shape (3, N) or (3,) representing unit direction vectors.
    """
    az_rad = np.radians(az_deg)
    alt_rad = np.radians(alt_deg)
    
    cos_alt = np.cos(alt_rad)
    sin_alt = np.sin(alt_rad)
    cos_az = np.cos(az_rad)
    sin_az = np.sin(az_rad)
    
    n = cos_alt * cos_az
    e = cos_alt * sin_az
    up = sin_alt
    
    return np.vstack((n, e, up))


def get_camera_basis(
    cam_az_deg: float,
    cam_alt_deg: float,
    cam_roll_deg: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute orthonormal camera basis vectors (right, up, forward) in the local NEU frame.
    
    - Forward (f): Boresight pointing direction along the optical axis into the scene.
    - Right (r): Camera horizontal axis (+x on screen pointing right).
    - Up (u): Camera vertical axis (+y on screen pointing top).
    
    Zenith / Nadir singularity protection:
    Instead of calculating right = f x (0,0,1) / ||f x (0,0,1)||, which has a 0/0 singularity
    when alt = 90 deg or -90 deg, we derive the base right and up vectors directly from azimuth:
      f = [cos(h)*cos(A), cos(h)*sin(A), sin(h)]
      r_base = [-sin(A), cos(A), 0]
      u_base = [-sin(h)*cos(A), -sin(h)*sin(A), cos(h)]
    These vectors are strictly orthonormal for all h in [-90, 90] and A in [0, 360],
    and roll rotation is applied in the (r_base, u_base) plane perpendicular to f.
    """
    az_rad = np.radians(cam_az_deg)
    alt_rad = np.radians(cam_alt_deg)
    roll_rad = np.radians(cam_roll_deg)
    
    cos_a = np.cos(az_rad)
    sin_a = np.sin(az_rad)
    cos_h = np.cos(alt_rad)
    sin_h = np.sin(alt_rad)
    
    # Forward boresight vector
    f = np.array([cos_h * cos_a, cos_h * sin_a, sin_h], dtype=np.float64)
    
    # Base right vector (perpendicular to f and zenith for non-vertical, continuous at zenith)
    r_base = np.array([-sin_a, cos_a, 0.0], dtype=np.float64)
    
    # Base up vector = f x r_base
    u_base = np.array([-sin_h * cos_a, -sin_h * sin_a, cos_h], dtype=np.float64)
    
    # Apply roll rotation around f (optical axis)
    cos_roll = np.cos(roll_rad)
    sin_roll = np.sin(roll_rad)
    
    r = cos_roll * r_base + sin_roll * u_base
    u = -sin_roll * r_base + cos_roll * u_base
    
    # Ensure numerical normalization
    r = r / np.linalg.norm(r)
    u = u / np.linalg.norm(u)
    f = f / np.linalg.norm(f)
    
    return r, u, f


def project_gnomonic(
    az_deg: np.ndarray,
    alt_deg: np.ndarray,
    cam_az_deg: float,
    cam_alt_deg: float,
    cam_roll_deg: float = 0.0,
    fov_h_deg: float = 60.0,
    fov_v_deg: float = 40.0,
    margin: float = 1.2,
    min_alt_deg: float = -2.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Project celestial coordinates (Azimuth, Altitude) to 2D normalized screen coordinates.
    
    Parameters:
    - az_deg, alt_deg: 1D numpy arrays of object coordinates.
    - cam_az_deg, cam_alt_deg, cam_roll_deg: Camera orientation.
    - fov_h_deg, fov_v_deg: Horizontal and vertical FOV.
    - margin: Screen margin filter (default 1.2 for 20% margin).
    - min_alt_deg: Minimum altitude threshold (default -2.0 deg).
    
    Returns:
    - screen_x: 1D array of normalized horizontal screen coordinates [-1.0, 1.0] corresponds to FOV.
    - screen_y: 1D array of normalized vertical screen coordinates [-1.0, 1.0] corresponds to FOV.
    - visible_mask: Boolean mask of objects that are visible within margin and above min_alt.
    """
    r, u, f = get_camera_basis(cam_az_deg, cam_alt_deg, cam_roll_deg)
    
    # Convert object coordinates to unit 3D vectors: shape (3, N)
    v = azalt_to_cartesian_neu(az_deg, alt_deg)
    
    # Coordinates in camera frame:
    # X_c = r . v
    # Y_c = u . v
    # Z_c = f . v (depth along boresight)
    x_c = np.dot(r, v)
    y_c = np.dot(u, v)
    z_c = np.dot(f, v)
    
    # Half FOV tangents
    tan_half_fov_h = np.tan(np.radians(fov_h_deg / 2.0))
    tan_half_fov_v = np.tan(np.radians(fov_v_deg / 2.0))
    
    # Prevent division by zero or negative depth (behind camera)
    in_front = z_c > 1e-6
    
    # Initialize screen coordinates
    screen_x = np.full_like(x_c, np.nan, dtype=np.float64)
    screen_y = np.full_like(y_c, np.nan, dtype=np.float64)
    
    # Perspective division
    screen_x[in_front] = (x_c[in_front] / z_c[in_front]) / tan_half_fov_h
    screen_y[in_front] = (y_c[in_front] / z_c[in_front]) / tan_half_fov_v
    
    # Visibility conditions:
    # 1. in front of camera (z_c > 0)
    # 2. altitude >= min_alt_deg (default -2.0)
    # 3. |screen_x| <= margin (default 1.2)
    # 4. |screen_y| <= margin (default 1.2)
    visible_mask = (
        in_front
        & (alt_deg >= min_alt_deg)
        & (np.abs(screen_x) <= margin)
        & (np.abs(screen_y) <= margin)
    )
    
    return screen_x, screen_y, visible_mask
