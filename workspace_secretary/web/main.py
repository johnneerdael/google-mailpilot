"""
Web UI entrypoint - runs the FastAPI web server.
"""

import os
import sys
import logging
import uvicorn

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def main():
    from workspace_secretary.web import web_app
    from workspace_secretary.web.routes import (
        inbox,
        thread,
        search,
        actions,
        compose,
        calendar,
        analysis,
        dashboard,
    )

    web_app.include_router(dashboard.router)
    web_app.include_router(inbox.router)
    web_app.include_router(thread.router)
    web_app.include_router(search.router)
    web_app.include_router(actions.router)
    web_app.include_router(compose.router)
    web_app.include_router(calendar.router)
    web_app.include_router(analysis.router)

    host = os.environ.get("WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("WEB_PORT", "8080"))

    logger.info(f"Starting Secretary Web UI on {host}:{port}")

    uvicorn.run(
        web_app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
