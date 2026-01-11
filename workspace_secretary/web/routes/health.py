import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from workspace_secretary.web.auth import Session, require_auth
from workspace_secretary.web.engine_client import get_client

router = APIRouter()


@router.get("/api/health/services")
async def get_services_health(session: Session = Depends(require_auth)):
    services = {
        "engine": {"status": "unknown", "error": None},
        "imap": {"status": "unknown", "error": None},
        "smtp": {"status": "unknown", "error": None},
        "calendar": {"status": "unknown", "error": None},
    }

    try:
        client = await get_client()
        response = await client.get("/health")
        if response.status_code == 200:
            services["engine"]["status"] = "healthy"

            engine_data = response.json()
            if "imap" in engine_data:
                services["imap"] = engine_data["imap"]
            if "smtp" in engine_data:
                services["smtp"] = engine_data["smtp"]
            if "calendar" in engine_data:
                services["calendar"] = engine_data["calendar"]
        else:
            services["engine"]["status"] = "degraded"
            services["engine"]["error"] = f"HTTP {response.status_code}"
    except (httpx.ConnectError, httpx.RequestError) as e:
        services["engine"]["status"] = "down"
        services["engine"]["error"] = str(e)
    except Exception as e:
        services["engine"]["status"] = "error"
        services["engine"]["error"] = str(e)

    overall_healthy = all(
        s["status"] in ["healthy", "unknown"] for s in services.values()
    )

    return JSONResponse(
        content={
            "status": "healthy" if overall_healthy else "degraded",
            "services": services,
        }
    )
