"""OAuth token storage + refresh.

LinkedIn access tokens last 60 days; refresh tokens last 365 days. The plan is
emphatic: build storage + auto-refresh from day one, and alert before the
refresh token lapses. This module owns that.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from linkedin_agent.config import Settings
from linkedin_agent.db import connect

PROVIDER = "linkedin"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

# Refresh proactively when the access token has this little life left.
ACCESS_REFRESH_MARGIN_S = 5 * 24 * 3600  # 5 days
# Warn the user this far ahead of the refresh token's hard expiry.
REFRESH_WARN_MARGIN_S = 14 * 24 * 3600  # 14 days


@dataclass
class StoredToken:
    access_token: str
    refresh_token: str | None
    access_expires_at: int
    refresh_expires_at: int | None
    scope: str | None
    member_urn: str | None

    @property
    def access_seconds_left(self) -> int:
        return int(self.access_expires_at - time.time())

    @property
    def refresh_seconds_left(self) -> int | None:
        if self.refresh_expires_at is None:
            return None
        return int(self.refresh_expires_at - time.time())

    @property
    def access_valid(self) -> bool:
        return self.access_seconds_left > 0

    @property
    def needs_refresh(self) -> bool:
        return self.access_seconds_left <= ACCESS_REFRESH_MARGIN_S

    @property
    def refresh_expiring_soon(self) -> bool:
        left = self.refresh_seconds_left
        return left is not None and left <= REFRESH_WARN_MARGIN_S


def save_token(
    settings: Settings,
    token_response: dict,
    *,
    member_urn: str | None = None,
) -> StoredToken:
    """Persist a token endpoint response. Preserves member_urn/refresh_token
    across refreshes when the new response omits them."""
    now = int(time.time())
    with connect(settings.db_path) as conn:
        existing = conn.execute(
            "SELECT refresh_token, refresh_expires_at, member_urn, scope "
            "FROM oauth_tokens WHERE provider = ?",
            (PROVIDER,),
        ).fetchone()

        access_token = token_response["access_token"]
        expires_in = int(token_response.get("expires_in", 0))
        access_expires_at = now + expires_in

        refresh_token = token_response.get("refresh_token")
        refresh_expires_in = token_response.get("refresh_token_expires_in")
        if refresh_token:
            refresh_expires_at = now + int(refresh_expires_in) if refresh_expires_in else None
        elif existing:
            # Refresh response without a new refresh token — keep the old one.
            refresh_token = existing["refresh_token"]
            refresh_expires_at = existing["refresh_expires_at"]
        else:
            refresh_expires_at = None

        scope = token_response.get("scope") or (existing["scope"] if existing else None)
        if member_urn is None and existing:
            member_urn = existing["member_urn"]

        conn.execute(
            """
            INSERT INTO oauth_tokens
                (provider, access_token, refresh_token, access_expires_at,
                 refresh_expires_at, scope, member_urn, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                access_expires_at=excluded.access_expires_at,
                refresh_expires_at=excluded.refresh_expires_at,
                scope=excluded.scope,
                member_urn=excluded.member_urn,
                updated_at=excluded.updated_at
            """,
            (
                PROVIDER, access_token, refresh_token, access_expires_at,
                refresh_expires_at, scope, member_urn, now,
            ),
        )

    return StoredToken(
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        scope=scope,
        member_urn=member_urn,
    )


def load_token(settings: Settings) -> StoredToken | None:
    with connect(settings.db_path) as conn:
        row = conn.execute(
            "SELECT * FROM oauth_tokens WHERE provider = ?", (PROVIDER,)
        ).fetchone()
    if row is None:
        return None
    return StoredToken(
        access_token=row["access_token"],
        refresh_token=row["refresh_token"],
        access_expires_at=row["access_expires_at"],
        refresh_expires_at=row["refresh_expires_at"],
        scope=row["scope"],
        member_urn=row["member_urn"],
    )


def refresh_access_token(settings: Settings, token: StoredToken) -> StoredToken:
    """Exchange the stored refresh token for a fresh access token."""
    if not token.refresh_token:
        raise RuntimeError("No refresh token stored — re-run `linkedin-agent auth`.")
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
            "client_id": settings.linkedin_client_id,
            "client_secret": settings.linkedin_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return save_token(settings, resp.json(), member_urn=token.member_urn)


def get_valid_token(settings: Settings) -> StoredToken:
    """Load the token, refreshing it if it's expired or near expiry."""
    token = load_token(settings)
    if token is None:
        raise RuntimeError(
            "Not authenticated with LinkedIn. Run `linkedin-agent auth` first."
        )
    if token.needs_refresh:
        token = refresh_access_token(settings, token)
    return token
