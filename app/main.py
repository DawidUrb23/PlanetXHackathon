import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.astro_engine import AstroEngine
from app.schemas import (
    SkyRequest,
    SkyResponse,
    TelemetryUploadRequest,
    TelemetryUploadResponse,
)

logger = logging.getLogger("ar_sky_backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Load ephemeris, star catalogs, and Messier catalogs once into memory at startup.
    This guarantees zero disk and network operations inside request endpoints.
    """
    data_dir = Path("data")
    if not (data_dir / "de421.bsp").exists():
        raise RuntimeError("Astronomical data files not found in data/. Run setup_data.py first.")
    
    app.state.astro_engine = AstroEngine(data_dir=data_dir)
    yield


app = FastAPI(
    title="AR Sky Backend API",
    description="Vectorized Astronomical Engine and Perspective Projection for AR Mobile Clients",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration for mobile clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", status_code=status.HTTP_200_OK)
@app.get("/healthy", status_code=status.HTTP_200_OK)
def health_check():
    """Health check endpoint for Docker / mobile diagnostic."""
    return {"status": "healthy", "service": "ar-sky-backend"}


@app.post("/upload", response_model=TelemetryUploadResponse, status_code=status.HTTP_200_OK)
async def upload_telemetry(payload: TelemetryUploadRequest, req: Request) -> TelemetryUploadResponse:
    """
    Direct endpoint for Android uploadPhotoToServer function.
    Receives JSON telemetry (pitch, azimuth, roll, lat, lon, gyro, accel, timestamp),
    computes visible celestial objects in the camera view, and returns them to the phone.
    """
    engine: AstroEngine = req.app.state.astro_engine
    try:
        sky_req = payload.to_sky_request()
        visible = engine.compute_visible(sky_req)
        
        logger.info(
            f"[/upload] Received: lat={sky_req.latitude:.4f}, lon={sky_req.longitude:.4f}, "
            f"az={sky_req.azimuth:.1f}°, alt={sky_req.altitude:.1f}°, roll={sky_req.roll:.1f}° -> "
            f"Computed {len(visible)} visible objects"
        )
        
        return TelemetryUploadResponse(
            status="success",
            message=f"Pomyślnie zidentyfikowano {len(visible)} obiektów na niebie",
            count=len(visible),
            objects=visible,
        )
    except Exception as e:
        logger.error(f"Error processing /upload: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error computing visible astronomical objects: {str(e)}",
        )


@app.post("/api/v1/sky/visible", response_model=SkyResponse, status_code=status.HTTP_200_OK)
def get_visible_sky_objects(request: SkyRequest, req: Request) -> SkyResponse:
    """
    Compute astronomical objects currently inside the camera's field of view,
    projecting their topocentric positions onto normalized 2D screen coordinates.
    """
    engine: AstroEngine = req.app.state.astro_engine
    try:
        visible = engine.compute_visible(request)
        return SkyResponse(count=len(visible), objects=visible)
    except Exception as e:
        logger.error(f"Error processing /api/v1/sky/visible: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error computing visible astronomical objects: {str(e)}",
        )
