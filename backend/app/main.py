from fastapi import FastAPI, Response, status

from app.core.config import get_settings
from app.core.observability import init_sentry


def create_app() -> FastAPI:
    settings = get_settings()
    init_sentry(settings.sentry_dsn, settings.sentry_environment)
    app = FastAPI(title="CBAM API")

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(response: Response) -> dict[str, str]:
        # DB, storage and Redis checks arrive with Phase 1; until then nothing is probed.
        response.status_code = status.HTTP_200_OK
        return {"status": "ok"}

    return app


app = create_app()
