import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response, status

from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import bind_context, clear_context, configure_logging
from app.core.observability import init_sentry


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_sentry(settings.sentry_dsn, settings.sentry_environment)
    app = FastAPI(title="CBAM API")
    install_error_handlers(app, type_base=settings.error_type_base)

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        clear_context()
        bind_context(request_id=request_id)
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(response: Response) -> dict[str, str]:
        # DB, storage and Redis checks arrive with Phase 1 step 5; nothing is probed yet.
        response.status_code = status.HTTP_200_OK
        return {"status": "ok"}

    return app


app = create_app()
