"""Reference-data routes (docs/API_SPEC.md, R1-050). Thin: permission, service, schema."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Response

from app.core.clock import Clock, get_clock
from app.core.config import Settings, get_settings
from app.core.tenancy import PlatformContext, require_refdata
from app.core.versioning import etag, parse_if_match
from app.modules.refdata import service
from app.modules.refdata.schemas import (
    DatasetOut,
    SourceOut,
    SourceStatusIn,
    VersionDetailOut,
    VersionOut,
)
from app.modules.refdata.service import Actor

router = APIRouter(prefix="/platform", tags=["reference data"])

Read = Annotated[PlatformContext, Depends(require_refdata("refdata:read"))]
Prepare = Annotated[PlatformContext, Depends(require_refdata("refdata:activate"))]
Decide = Annotated[PlatformContext, Depends(require_refdata("refdata:activate", recent_auth=True))]
Now = Annotated[Clock, Depends(get_clock)]


@router.get("/sources", response_model=list[SourceOut])
def list_sources(ctx: Read) -> list[dict[str, Any]]:
    with ctx.session() as s:
        return service.list_sources(s)


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: str, response: Response, ctx: Read) -> dict[str, Any]:
    with ctx.session() as s:
        source = service.get_source(s, source_id)
    response.headers["ETag"] = etag(source["row_version"])
    return source


@router.post("/sources/{source_id}/status", response_model=SourceOut)
def set_source_status(
    source_id: str,
    body: SourceStatusIn,
    response: Response,
    ctx: Decide,
    clock: Now,
    if_match: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    expected = parse_if_match(if_match)
    with ctx.session() as s:
        source = service.set_source_status(
            s,
            Actor(ctx.user.user_id),
            clock.now(),
            source_id,
            expected_version=expected,
            status=body.status,
            reason=body.reason,
            commencement_date=body.commencement_date,
        )
    response.headers["ETag"] = etag(source["row_version"])
    return source


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(ctx: Read) -> list[dict[str, Any]]:
    with ctx.session() as s:
        return service.list_datasets(s)


@router.get("/datasets/{dataset}/versions", response_model=list[VersionOut])
def list_versions(dataset: str, ctx: Read) -> list[dict[str, Any]]:
    with ctx.session() as s:
        return service.list_versions(s, dataset)


@router.get("/datasets/{dataset}/versions/{version}", response_model=VersionDetailOut)
def get_version(dataset: str, version: str, response: Response, ctx: Read) -> dict[str, Any]:
    with ctx.session() as s:
        found = service.get_version(s, dataset, version)
    response.headers["ETag"] = etag(found["row_version"])
    return found


@router.post("/datasets/{dataset}/versions/{version}/impact")
def impact_report(dataset: str, version: str, ctx: Prepare, clock: Now) -> dict[str, Any]:
    """Dry run only: stores the report on the pending version, changes no reference data."""
    with ctx.session() as s:
        return service.build_impact_report(
            s, Actor(ctx.user.user_id), clock.now(), dataset, version
        )


@router.post("/datasets/{dataset}/versions/{version}/activate", response_model=VersionDetailOut)
def activate(
    dataset: str,
    version: str,
    response: Response,
    ctx: Decide,
    clock: Now,
    settings: Annotated[Settings, Depends(get_settings)],
    if_match: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    expected = parse_if_match(if_match)
    with ctx.session() as s:
        activated = service.activate_version(
            s,
            Actor(ctx.user.user_id),
            clock.now(),
            dataset,
            version,
            expected_version=expected,
            app_env=settings.app_env,
        )
    response.headers["ETag"] = etag(activated["row_version"])
    return activated
