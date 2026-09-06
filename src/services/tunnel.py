"""
Tunnel and network exposure service.

Coordinates status inspection and control for Tailscale Funnel / public tunnels.
"""

from __future__ import annotations

from typing import Optional

from src.config import Settings, setup_logger
from src.schema import TunnelStatus
from src.providers import is_tailscale_installed, run_tailscale_json, run_tailscale_cmd

logger = setup_logger(Settings.LOG_DIR / "service.log", name="gitmanager.services.tunnel")


def get_tunnel_status(port: Optional[int] = None) -> TunnelStatus:
    """
    Inspect the system and Tailscale state to determine if Tailscale is installed,
    running, and if a Funnel proxy is active.
    """
    check_port = port or Settings.API_PORT

    if not is_tailscale_installed():
        return TunnelStatus(
            installed=False,
            running=False,
            funnel_active=False,
            port=check_port,
            error="Tailscale CLI is not installed",
        )

    # 1. Check general daemon status
    ok_status, status_data, err_status = run_tailscale_json(["status"])
    if not ok_status or not status_data:
        logger.warning(f"Tailscale status inspection failed: {err_status}")
        return TunnelStatus(
            installed=True,
            running=False,
            funnel_active=False,
            port=check_port,
            error=err_status or "Tailscale daemon is not running",
        )

    self_node = status_data.get("Self", {})
    dns_name = self_node.get("DNSName", "").rstrip(".")
    backend_state = status_data.get("BackendState", "")
    is_running = backend_state.lower() == "running" if backend_state else True

    # 2. Check Funnel status
    ok_funnel, funnel_data, err_funnel = run_tailscale_json(["funnel", "status"])
    funnel_active = False
    funnel_url: Optional[str] = None

    if ok_funnel and funnel_data:
        # Check AllowFunnel map, e.g. {"node.domain.ts.net:443": true}
        allow_funnel = funnel_data.get("AllowFunnel", {})
        for target, active in allow_funnel.items():
            if active:
                funnel_active = True
                host = target.split(":")[0]
                funnel_url = f"https://{host}"
                break

        # Fallback check on Web handlers
        if not funnel_active and "Web" in funnel_data:
            web_map = funnel_data.get("Web", {})
            for target in web_map.keys():
                host = target.split(":")[0]
                funnel_active = True
                funnel_url = f"https://{host}"
                break

    # If funnel is active but no specific url was resolved from target keys, use dns_name
    if funnel_active and not funnel_url and dns_name:
        funnel_url = f"https://{dns_name}"

    return TunnelStatus(
        installed=True,
        running=is_running,
        funnel_active=funnel_active,
        domain=dns_name or None,
        funnel_url=funnel_url,
        port=check_port,
        error=None if is_running else "Tailscale daemon not in running state",
    )


def toggle_funnel(enable: bool, port: Optional[int] = None) -> tuple[bool, str]:
    """Start or stop the Tailscale background funnel proxy."""
    target_port = port or Settings.API_PORT

    if enable:
        logger.info(f"Enabling Tailscale Funnel for port {target_port} ...")
        ok, msg = run_tailscale_cmd(["funnel", "--bg", str(target_port)])
    else:
        logger.info("Disabling Tailscale Funnel ...")
        ok, msg = run_tailscale_cmd(["funnel", "--https=443", "off"])

    if ok:
        logger.info(f"Tailscale Funnel toggle successful: {msg}")
    else:
        logger.warning(f"Tailscale Funnel toggle failed: {msg}")

    return ok, msg
