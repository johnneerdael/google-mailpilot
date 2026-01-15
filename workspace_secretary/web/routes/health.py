import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from workspace_secretary.web.auth import Session, require_auth
from workspace_secretary.web.engine_client import get_client

router = APIRouter()

ENGINE_HEALTH_PATHS = ["/health", "/api/health", "/api/status"]


async def _fetch_engine_health(client) -> tuple[str, dict | None, str | None]:
    """Return (status, details, error) from the engine health endpoint."""
    last_error = None
    for path in ENGINE_HEALTH_PATHS:
        response = await client.get(path)
        if response.status_code == 200:
            payload = response.json()
            if isinstance(payload, dict):
                status = payload.get("status") or payload.get("health")
                error = payload.get("error")
                if status in {"down", "critical"}:
                    return "down", payload, error
                if status in {"degraded", "unknown", "warning"}:
                    return (
                        "degraded",
                        payload,
                        error or "Engine reported unknown status",
                    )
                if status in {"healthy", "running", "ok"} and not error:
                    return "healthy", payload, None
            last_error = payload.get("error") if isinstance(payload, dict) else None
        else:
            last_error = f"HTTP {response.status_code}"
    return "degraded", None, last_error or "Engine health endpoint unavailable"


@router.get("/api/health/services")
async def get_services_health(session: Session = Depends(require_auth)):
    services = {
        "engine": {"status": "unknown", "error": None},
    }

    overall_status = "degraded"

    try:
        client = await get_client()
        status, details, error = await _fetch_engine_health(client)
        services["engine"]["status"] = status
        if details:
            services["engine"]["details"] = details
        services["engine"]["error"] = error
    except (httpx.ConnectError, httpx.RequestError) as exc:
        services["engine"] = {"status": "down", "error": str(exc)}
    except Exception as exc:
        services["engine"] = {"status": "error", "error": str(exc)}

    if all(s["status"] == "healthy" for s in services.values()):
        overall_status = "healthy"

    return JSONResponse(
        content={
            "status": overall_status,
            "services": services,
        }
    )
