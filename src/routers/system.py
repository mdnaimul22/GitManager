"""
System and network endpoints.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from src.schema import TunnelStatus
from src.services import get_tunnel_status, toggle_funnel
from src.config import Settings, setup_logger

logger = setup_logger(Settings.LOG_DIR / "router.log", name="gitmanager.routers.system")

router = APIRouter(
    prefix="/api/system",
    tags=["system"],
)


class FunnelToggleRequest(BaseModel):
    enable: bool


@router.get("/tunnel", response_model=TunnelStatus)
async def api_get_tunnel_status():
    """Return the current Tailscale tunnel / funnel status."""
    return get_tunnel_status()


@router.post("/tunnel/funnel")
async def api_toggle_funnel(req: FunnelToggleRequest):
    """Enable or disable Tailscale funnel."""
    ok, msg = toggle_funnel(req.enable)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to toggle tunnel: {msg}",
        )
    return {"status": "ok", "message": msg, "tunnel": get_tunnel_status()}
