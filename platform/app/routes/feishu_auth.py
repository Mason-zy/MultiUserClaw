"""Feishu SSO routes: /login + /callback + /token (TASK-1).

Mounted under ``/api/auth`` prefix alongside the existing username/password
routes. The Feishu user_access_token is used only inside ``feishu_client`` to
fetch user info once; session credentials are the platform's own HS256 JWT
(via ``create_access_token`` / ``create_refresh_token``), so ``get_current_user``
needs no changes to protect feishu-login sessions.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import (
    create_access_token,
    create_refresh_token,
    get_or_create_feishu_user,
)
from app.config import settings
from app.db.engine import get_db
from app.routes.auth import TokenResponse
from app.services import feishu_client, oauth_state

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _frontend_redirect_url() -> str:
    """Where the browser lands after the OAuth round-trip.

    Defaults to a relative ``/login/feishu`` so the route works even when
    ``PLATFORM_FEISHU_FRONTEND_REDIRECT_URL`` is unset (local dev / tests).
    """
    return settings.feishu_frontend_redirect_url or "/login/feishu"


def _error_redirect(error: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"{_frontend_redirect_url()}?{urlencode({'error': error})}",
        status_code=status.HTTP_302_FOUND,
    )


# ---------------------------------------------------------------------------
# GET /feishu/login — redirect to Feishu authorize page
# ---------------------------------------------------------------------------

@router.get("/feishu/login")
async def feishu_login():
    """Issue a CSRF state and 302 to the Feishu authorize endpoint."""
    state = oauth_state.create_state("web")
    params = {
        "app_id": settings.feishu_app_id,
        "redirect_uri": settings.feishu_callback_url,
        "response_type": "code",
        "state": state,
    }
    authorize_url = (
        f"{settings.feishu_base_url}/authen/v1/authorize?{urlencode(params)}"
    )
    return RedirectResponse(url=authorize_url, status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# GET /feishu/callback — browser redirect flow
# ---------------------------------------------------------------------------

async def _resolve_feishu_user(code: str, db: AsyncSession):
    """Shared helper: code → claims → local user. Used by /callback and /token."""
    claims = await feishu_client.get_full_user_info(code)
    sub = claims.get("sub", "")
    if not sub:
        raise HTTPException(status_code=502, detail="飞书未返回用户标识")
    sso_uid = f"feishu:{sub}"
    user = await get_or_create_feishu_user(
        db,
        sso_uid=sso_uid,
        display_name=claims.get("name", ""),
        email=claims.get("email", ""),
    )
    return user


@router.get("/feishu/callback")
async def feishu_callback(
    code: str,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """OAuth callback: validate state, get user, issue JWT, redirect to frontend."""
    if not state:
        return _error_redirect("missing_state")
    record = oauth_state.consume_state_record(state)
    if record is None:
        return _error_redirect("invalid_or_expired_state")

    try:
        user = await _resolve_feishu_user(code, db)
    except HTTPException:
        return _error_redirect("feishu_exchange_failed")

    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id)
    params = {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    return RedirectResponse(
        url=f"{_frontend_redirect_url()}?{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )


# ---------------------------------------------------------------------------
# POST /feishu/token — API flow (no redirect), mirrors /api/auth/login shape
# ---------------------------------------------------------------------------

@router.post("/feishu/token", response_model=TokenResponse)
async def feishu_token(code: str, db: AsyncSession = Depends(get_db)):
    """Exchange a Feishu auth code for a platform TokenResponse (non-browser)."""
    try:
        user = await _resolve_feishu_user(code, db)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="飞书登录失败，请稍后重试",
        ) from exc
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        username=user.username,
        role=user.role,
    )
