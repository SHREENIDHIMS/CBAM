from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Engine

from app.core.auth import AuthenticatedUser
from app.core.tenancy import get_current_user, get_engine_dep
from app.modules.identity.schemas import MeOut
from app.modules.identity.service import describe_user

router = APIRouter(tags=["identity"])


@router.get("/me", response_model=MeOut)
def me(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    engine: Annotated[Engine, Depends(get_engine_dep)],
) -> MeOut:
    return describe_user(engine, user)
