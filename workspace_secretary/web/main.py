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
    from workspace_secretary.web import web_app, init_web_app
    from workspace_secretary.web.routes import (
        inbox,
        thread,
        search,
        actions,
        compose,
        calendar,
        contacts,
        analysis,
        dashboard,
        chat,
        settings,
        notifications,
        bulk,
        admin,
        sync,
        health,
    )
    from workspace_secretary.web.llm_client import init_llm_client
    from workspace_secretary.config import load_config

    config = load_config()
    init_web_app(config.web if config else None)

    if config and config.web and config.web.agent:
        init_llm_client(config.web.agent)
    else:
        init_llm_client(None)

    web_app.include_router(dashboard.router)
    web_app.include_router(inbox.router)
    web_app.include_router(thread.router)
    web_app.include_router(search.router)
    web_app.include_router(actions.router)
    web_app.include_router(compose.router)
    web_app.include_router(calendar.router)
    web_app.include_router(contacts.router)
    web_app.include_router(analysis.router)
    web_app.include_router(chat.router)
    web_app.include_router(settings.router)
    web_app.include_router(notifications.router)
    web_app.include_router(bulk.router)
    web_app.include_router(admin.router)
    web_app.include_router(sync.router)
    web_app.include_router(health.router)

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
