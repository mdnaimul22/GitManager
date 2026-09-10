from fastapi import APIRouter, Depends, HTTPException, status

from src.schema import TunnelStatus, FunnelToggleRequest, FunnelToggleResponse
from src.services import TunnelService
from src.config import Settings, setup_logger
from .auth import require_auth

logger = setup_logger(Settings.LOG_DIR / "router.log", name="gitmanager.routers.system")

router = APIRouter(
    prefix="/api/system",
    tags=["system"],
    dependencies=[Depends(require_auth)],
)


@router.get("/tunnel", response_model=TunnelStatus)
async def api_get_tunnel_status():
    """Return the current Tailscale tunnel / funnel status."""
    return TunnelService().get_status()


@router.post("/tunnel/funnel", response_model=FunnelToggleResponse)
async def api_toggle_funnel(req: FunnelToggleRequest):
    """Enable or disable Tailscale funnel."""
    svc = TunnelService()
    ok, msg = svc.toggle(req.enable)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to toggle tunnel: {msg}",
        )
    return FunnelToggleResponse(status="ok", message=msg, tunnel=svc.get_status())

