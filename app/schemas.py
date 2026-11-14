from datetime import datetime, timezone
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


def parse_flexible_timestamp(val: Any) -> datetime:
    """
    Safely parse timestamps in various formats (ISO 8601, epoch milliseconds, epoch seconds, custom strings).
    Falls back to current UTC time if missing or unparseable.
    """
    if val is None or val == "" or str(val).strip().lower() in ("null", "none"):
        return datetime.now(timezone.utc)
    if isinstance(val, (int, float)):
        # If timestamp is in ms (epoch millis is ~ 1.7e12), divide by 1000
        if val > 1e11:
            val = val / 1000.0
        return datetime.fromtimestamp(val, tz=timezone.utc)
    if isinstance(val, str):
        val_clean = val.strip()
        # Check if numeric string (millis or seconds)
        try:
            num = float(val_clean)
            if num > 1e11:
                num = num / 1000.0
            return datetime.fromtimestamp(num, tz=timezone.utc)
        except ValueError:
            pass
        # Try ISO parsing
        try:
            dt = datetime.fromisoformat(val_clean.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
        # Try dateutil parser
        try:
            from dateutil import parser
            dt = parser.parse(val_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


class SkyRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Observer latitude in degrees (-90 to 90)")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Observer longitude in degrees (-180 to 180)")
    elevation: float = Field(default=0.0, ge=-500.0, le=100000.0, description="Elevation above sea level in meters")
    timestamp: datetime = Field(..., description="Observation timestamp in ISO 8601 format")
    azimuth: float = Field(..., ge=0.0, le=360.0, description="Camera boresight azimuth (0-360, 0=N, 90=E, 180=S, 270=W)")
    altitude: float = Field(..., ge=-90.0, le=90.0, description="Camera boresight altitude (-90 to 90, 0=horizon, 90=zenith)")
    roll: float = Field(default=0.0, description="Phone roll around optical axis in degrees")
    fov_horizontal: float = Field(default=60.0, gt=0.0, lt=180.0, description="Camera horizontal field of view in degrees")
    fov_vertical: float = Field(default=40.0, gt=0.0, lt=180.0, description="Camera vertical field of view in degrees")

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class AstroObject(BaseModel):
    id: str
    name: str
    type: Literal["planet", "star", "messier"]
    magnitude: Optional[float] = None
    azimuth: float
    altitude: float
    screen_x: float
    screen_y: float


class SkyResponse(BaseModel):
    count: int
    objects: List[AstroObject]


class TelemetryUploadRequest(BaseModel):
    """
    Flexible schema accepting raw Android telemetry payload from mobile phone.
    Accepts pitch (mapped to altitude), IMU gyro/accel data, and flexible timestamp formats.
    """
    model_config = ConfigDict(extra="allow")

    timestamp: Optional[Any] = None
    latitude: float = 0.0
    longitude: float = 0.0
    elevation: Optional[float] = 0.0

    azimuth: float = 0.0
    pitch: Optional[float] = None
    altitude: Optional[float] = None
    roll: float = 0.0

    fov_horizontal: float = 60.0
    fov_vertical: float = 40.0

    # Optional IMU sensors
    gyroX: Optional[float] = None
    gyroY: Optional[float] = None
    gyroZ: Optional[float] = None
    accelX: Optional[float] = None
    accelY: Optional[float] = None
    accelZ: Optional[float] = None

    def to_sky_request(self) -> SkyRequest:
        # Use altitude if provided, else pitch, fallback 0.0
        calc_alt = self.altitude if self.altitude is not None else (self.pitch if self.pitch is not None else 0.0)
        calc_alt = max(-90.0, min(90.0, float(calc_alt)))
        calc_az = float(self.azimuth) % 360.0
        calc_lat = max(-90.0, min(90.0, float(self.latitude)))
        calc_lon = max(-180.0, min(180.0, float(self.longitude)))
        parsed_dt = parse_flexible_timestamp(self.timestamp)

        return SkyRequest(
            latitude=calc_lat,
            longitude=calc_lon,
            elevation=float(self.elevation or 0.0),
            timestamp=parsed_dt,
            azimuth=calc_az,
            altitude=calc_alt,
            roll=float(self.roll or 0.0),
            fov_horizontal=float(self.fov_horizontal or 60.0),
            fov_vertical=float(self.fov_vertical or 40.0),
        )


class TelemetryUploadResponse(BaseModel):
    status: str = "success"
    message: str = "Telemetria odebrana i przetworzona pomyślnie"
    count: int
    objects: List[AstroObject]
