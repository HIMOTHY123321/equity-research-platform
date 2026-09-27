"""Phase 16/16.1: signup/login/logout/me -- thin orchestration over
app.auth.service, same convention every other route module follows.

Phase 16.1: signup/login now set an HttpOnly session cookie (the primary,
browser-facing transport -- see app.auth.cookies) AND still return the raw
token in the JSON body, kept only for non-browser callers (tests, scripts)
that cannot rely on a cookie jar. Every issued token is paired with a
`user_sessions` row (app.auth.sessions) so `logout` can actually revoke it
before its own `exp` claim would.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.cookies import SESSION_COOKIE_NAME, clear_session_cookie, set_session_cookie
from app.auth.dependencies import get_current_user, get_session_repository, get_user_repository
from app.auth.repository import UserRepository
from app.auth.schemas import LoginRequest, SignupRequest, TokenResponse, UserOut
from app.auth.security import InvalidTokenError, create_access_token, decode_access_token
from app.auth.service import EmailAlreadyRegisteredError, InvalidCredentialsError, authenticate, signup
from app.auth.sessions import SessionRepository
from app.config import Settings, get_settings
from app.database.models import User
from app.rate_limiting import auth_rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer_scheme = HTTPBearer(auto_error=False)


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        status=user.status,
        role=user.role,
        plan=user.plan,
        timezone=user.timezone,
        created_at=user.created_at,
    )


def _issue_session(
    response: Response,
    user: User,
    session_repository: SessionRepository,
    settings: Settings,
) -> TokenResponse:
    issued = create_access_token(user.id, settings=settings)
    session_repository.create(user_id=user.id, jti=issued.jti, expires_at=issued.expires_at)
    set_session_cookie(
        response, issued.token, settings=settings, max_age_seconds=settings.access_token_ttl_minutes * 60
    )
    return TokenResponse(access_token=issued.token, user=_user_out(user))


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(auth_rate_limit)],
)
def signup_route(
    payload: SignupRequest,
    response: Response,
    user_repository: UserRepository = Depends(get_user_repository),
    session_repository: SessionRepository = Depends(get_session_repository),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    try:
        user = signup(user_repository, email=payload.email, password=payload.password)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _issue_session(response, user, session_repository, settings)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(auth_rate_limit)])
def login_route(
    payload: LoginRequest,
    response: Response,
    user_repository: UserRepository = Depends(get_user_repository),
    session_repository: SessionRepository = Depends(get_session_repository),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    try:
        user = authenticate(user_repository, email=payload.email, password=payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _issue_session(response, user, session_repository, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def logout_route(
    response: Response,
    session_cookie: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    session_repository: SessionRepository = Depends(get_session_repository),
    settings: Settings = Depends(get_settings),
) -> None:
    """Revokes exactly the presented session (never every session this user
    has -- see SessionRepository.revoke_all_for_user for the disable-user
    case), then clears the cookie regardless of whether a valid token was
    even presented -- logout must always succeed from the browser's point
    of view."""
    # Same priority as get_current_user (app.auth.dependencies._extract_
    # token): an explicit Authorization header wins over an ambient cookie.
    token = credentials.credentials if credentials else session_cookie
    if token is not None:
        try:
            payload = decode_access_token(token)
        except InvalidTokenError:
            payload = None
        if payload is not None:
            session_repository.revoke(payload.jti)
    clear_session_cookie(response, settings=settings)


@router.get("/me", response_model=UserOut)
def me_route(current_user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(current_user)
