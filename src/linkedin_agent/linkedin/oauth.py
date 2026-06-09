"""3-legged OAuth consent flow via a tiny local FastAPI app.

Run `linkedin-agent auth`: it starts a server on the redirect URI's port,
prints (and opens) the LinkedIn consent URL. You log in once, LinkedIn
redirects back to /callback, we exchange the code for tokens, fetch your
person URN from /userinfo, store everything, and shut the server down.
"""

from __future__ import annotations

import secrets
import threading
import urllib.parse
import webbrowser

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from linkedin_agent.config import Settings, get_settings
from linkedin_agent.linkedin import tokens

AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"


def build_authorize_url(settings: Settings, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.linkedin_client_id,
        "redirect_uri": settings.linkedin_redirect_uri,
        "scope": settings.linkedin_scopes,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(settings: Settings, code: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.linkedin_redirect_uri,
            "client_id": settings.linkedin_client_id,
            "client_secret": settings.linkedin_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_member_urn(access_token: str) -> str:
    """OpenID /userinfo returns `sub`; the post author URN is urn:li:person:{sub}."""
    resp = httpx.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    sub = resp.json().get("sub")
    if not sub:
        raise RuntimeError(
            "userinfo returned no `sub`. Make sure the 'Sign In with LinkedIn "
            "using OpenID Connect' product is enabled and `openid profile` "
            "scopes were granted."
        )
    return f"urn:li:person:{sub}"


def _redirect_port(redirect_uri: str) -> int:
    parsed = urllib.parse.urlparse(redirect_uri)
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def run_auth_flow(settings: Settings | None = None, *, open_browser: bool = True) -> None:
    """Blocking: serve the callback, drive consent, store tokens, then stop."""
    settings = settings or get_settings()
    settings.require_linkedin()

    state = secrets.token_urlsafe(24)
    result: dict = {}
    done = threading.Event()

    app = FastAPI()

    @app.get("/callback", response_class=HTMLResponse)
    def callback(request: Request) -> HTMLResponse:  # noqa: ANN202
        params = request.query_params
        if params.get("error"):
            result["error"] = f"{params.get('error')}: {params.get('error_description')}"
            done.set()
            return HTMLResponse(f"<h2>Authorization failed</h2><p>{result['error']}</p>", 400)
        if params.get("state") != state:
            done.set()
            raise HTTPException(400, "State mismatch — possible CSRF. Aborting.")
        code = params.get("code")
        if not code:
            done.set()
            raise HTTPException(400, "No authorization code returned.")

        token_response = exchange_code_for_token(settings, code)
        member_urn = fetch_member_urn(token_response["access_token"])
        stored = tokens.save_token(settings, token_response, member_urn=member_urn)
        result["member_urn"] = member_urn
        result["scope"] = stored.scope
        done.set()
        return HTMLResponse(
            "<h2>✅ LinkedIn connected</h2>"
            f"<p>Authenticated as <code>{member_urn}</code>.</p>"
            "<p>You can close this tab and return to the terminal.</p>"
        )

    port = _redirect_port(settings.linkedin_redirect_uri)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    authorize_url = build_authorize_url(settings, state)
    print("\nOpen this URL to authorize (it should open automatically):\n")
    print(f"  {authorize_url}\n")
    if open_browser:
        webbrowser.open(authorize_url)

    done.wait(timeout=300)
    server.should_exit = True
    thread.join(timeout=5)

    if "error" in result:
        raise RuntimeError(f"OAuth failed: {result['error']}")
    if "member_urn" not in result:
        raise RuntimeError("Timed out waiting for authorization (5 min).")

    print(f"✅ Stored tokens for {result['member_urn']} (scope: {result['scope']}).")
