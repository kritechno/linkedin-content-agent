"""LinkedIn Posts API client (the modern /rest/posts endpoint).

Text-only posting for Phase 0/4. Image posting (register upload → PUT bytes →
reference URN) is Phase 5 and intentionally not here yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from linkedin_agent.config import Settings, get_settings
from linkedin_agent.linkedin import tokens

POSTS_URL = "https://api.linkedin.com/rest/posts"
IMAGES_URL = "https://api.linkedin.com/rest/images?action=initializeUpload"


@dataclass
class PostResult:
    post_urn: str
    status_code: int


def _headers(settings: Settings, access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": settings.linkedin_api_version,
    }


def build_text_post_body(author_urn: str, text: str) -> dict:
    return {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }


def build_image_post_body(author_urn: str, text: str, image_urn: str, alt_text: str) -> dict:
    body = build_text_post_body(author_urn, text)
    body["content"] = {"media": {"id": image_urn, "altText": alt_text[:300]}}
    return body


def post_text(text: str, *, settings: Settings | None = None) -> PostResult:
    """Publish a text-only post as the authenticated member."""
    settings = settings or get_settings()
    settings.require_linkedin()
    token = tokens.get_valid_token(settings)
    if not token.member_urn:
        raise RuntimeError(
            "No member URN stored — re-run `linkedin-agent auth` so we can fetch "
            "your person URN from /userinfo."
        )

    body = build_text_post_body(token.member_urn, text)
    resp = httpx.post(
        POSTS_URL,
        json=body,
        headers=_headers(settings, token.access_token),
        timeout=30.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"LinkedIn post failed ({resp.status_code}): {resp.text}\n"
            "Common causes: stale LINKEDIN_API_VERSION, missing w_member_social "
            "scope, or an expired token."
        )
    return _result_from_response(resp)


def _result_from_response(resp: httpx.Response) -> PostResult:
    # The created post's URN comes back in the x-restli-id header (or x-linkedin-id).
    post_urn = (
        resp.headers.get("x-restli-id")
        or resp.headers.get("x-linkedin-id")
        or (resp.json().get("id", "") if resp.content else "")
    )
    return PostResult(post_urn=post_urn, status_code=resp.status_code)


# ── image posting (Phase 5): register → PUT bytes → post referencing the URN ──
def _register_image_upload(settings: Settings, token, *, owner_urn: str) -> tuple[str, str]:
    resp = httpx.post(
        IMAGES_URL,
        json={"initializeUploadRequest": {"owner": owner_urn}},
        headers=_headers(settings, token.access_token),
        timeout=30.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Image initializeUpload failed ({resp.status_code}): {resp.text}")
    value = resp.json()["value"]
    return value["uploadUrl"], value["image"]


def _upload_image_bytes(upload_url: str, image_path: str, access_token: str) -> None:
    data = Path(image_path).read_bytes()
    resp = httpx.put(
        upload_url,
        content=data,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=60.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Image byte upload failed ({resp.status_code}): {resp.text}")


def post_image(
    text: str,
    image_path: str,
    *,
    alt_text: str = "",
    settings: Settings | None = None,
) -> PostResult:
    """Publish a post with a single image (3-step dance)."""
    settings = settings or get_settings()
    settings.require_linkedin()
    token = tokens.get_valid_token(settings)
    if not token.member_urn:
        raise RuntimeError("No member URN stored — re-run `linkedin-agent auth`.")

    upload_url, image_urn = _register_image_upload(settings, token, owner_urn=token.member_urn)
    _upload_image_bytes(upload_url, image_path, token.access_token)
    body = build_image_post_body(token.member_urn, text, image_urn, alt_text or text[:200])
    resp = httpx.post(
        POSTS_URL, json=body, headers=_headers(settings, token.access_token), timeout=30.0
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"LinkedIn image post failed ({resp.status_code}): {resp.text}")
    return _result_from_response(resp)
