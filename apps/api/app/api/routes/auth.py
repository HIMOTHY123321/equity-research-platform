"""Phase 16 (§12): signup/login/me -- thin orchestration over
app.auth.service, same convention every other route module follows.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user, get_user_repository
from app.auth.repository import UserRepository
from app.auth.schemas import LoginRequest, SignupRequest, TokenResponse, UserOut
from app.auth.security import create_access_token
from app.auth.service import EmailAlreadyRegisteredError, InvalidCredentialsError, authenticate, signup
from app.database.models import User
from app.rate_limiting import auth_rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        status=user.status,
        role=user.role,
        timezone=user.timezone,
        created_at=user.created_at,
    )


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(auth_rate_limit)],
)
def signup_route(
    payload: SignupRequest, user_repository: UserRepository = Depends(get_user_repository)
) -> TokenResponse:
    try:
        user = signup(user_repository, email=payload.email, password=payload.password)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=_user_out(user))


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(auth_rate_limit)])
def login_route(
    payload: LoginRequest, user_repository: UserRepository = Depends(get_user_repository)
) -> TokenResponse:
    try:
        user = authenticate(user_repository, email=payload.email, password=payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me_route(current_user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(current_user)
