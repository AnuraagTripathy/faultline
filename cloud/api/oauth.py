"""Minimal OAuth helpers for Google and GitHub browser login."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from cloud.api.user_accounts import validate_email


@dataclass(frozen=True)
class OAuthProfile:
    provider: str
    provider_user_id: str
    email: str


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing env var: {name}")
    return value


def oauth_enabled(provider: str) -> bool:
    p = provider.lower()
    if p == "google":
        return bool(
            os.environ.get("FAULTLINE_OAUTH_GOOGLE_CLIENT_ID", "").strip()
            and os.environ.get("FAULTLINE_OAUTH_GOOGLE_CLIENT_SECRET", "").strip()
        )
    if p == "github":
        return bool(
            os.environ.get("FAULTLINE_OAUTH_GITHUB_CLIENT_ID", "").strip()
            and os.environ.get("FAULTLINE_OAUTH_GITHUB_CLIENT_SECRET", "").strip()
        )
    return False


def oauth_authorize_url(provider: str, *, redirect_uri: str, state: str) -> str:
    p = provider.lower()
    if p == "google":
        query = urllib.parse.urlencode(
            {
                "client_id": _env("FAULTLINE_OAUTH_GOOGLE_CLIENT_ID"),
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "prompt": "select_account",
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"
    if p == "github":
        query = urllib.parse.urlencode(
            {
                "client_id": _env("FAULTLINE_OAUTH_GITHUB_CLIENT_ID"),
                "redirect_uri": redirect_uri,
                "scope": "read:user user:email",
                "state": state,
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"
    raise ValueError(f"unsupported oauth provider: {provider}")


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
) -> Any:
    data = urllib.parse.urlencode(form).encode("utf-8") if form is not None else None
    req_headers = dict(headers or {})
    if form is not None:
        req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        req_headers.setdefault("Accept", "application/json")
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} from {url}: {detail}") from error
    if not body:
        return None
    return json.loads(body)


def _github_noreply_email(user: dict[str, Any]) -> str:
    user_id = user.get("id")
    login = str(user.get("login", "")).strip()
    if user_id and login:
        return f"{user_id}+{login}@users.noreply.github.com".lower()
    return ""


def _github_email_from_user(user: dict[str, Any], access_token: str) -> str:
    def _accept(candidate: str) -> str | None:
        addr = candidate.strip().lower()
        if not addr:
            return None
        try:
            validate_email(addr)
        except ValueError:
            return None
        return addr

    direct = _accept(str(user.get("email", "")))
    if direct:
        return direct

    try:
        emails_payload = _http_json(
            "GET",
            "https://api.github.com/user/emails",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "faultline-cloud",
            },
        )
    except RuntimeError:
        emails_payload = None

    if isinstance(emails_payload, list):
        verified = [item for item in emails_payload if item.get("verified")]
        primary = next((item for item in verified if item.get("primary")), None)
        chosen = primary or (verified[0] if verified else None)
        if chosen:
            accepted = _accept(str(chosen.get("email", "")))
            if accepted:
                return accepted

    return _github_noreply_email(user)


def exchange_code_for_profile(
    provider: str,
    *,
    code: str,
    redirect_uri: str,
) -> OAuthProfile:
    p = provider.lower()
    if p == "google":
        token = _http_json(
            "POST",
            "https://oauth2.googleapis.com/token",
            form={
                "client_id": _env("FAULTLINE_OAUTH_GOOGLE_CLIENT_ID"),
                "client_secret": _env("FAULTLINE_OAUTH_GOOGLE_CLIENT_SECRET"),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        if not isinstance(token, dict):
            raise RuntimeError("google token exchange returned invalid response")
        access_token = str(token.get("access_token", "")).strip()
        if not access_token:
            raise RuntimeError(
                f"google token exchange failed: {token.get('error_description') or token}"
            )
        profile = _http_json(
            "GET",
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if not isinstance(profile, dict):
            raise RuntimeError("google profile response invalid")
        email = str(profile.get("email", "")).strip().lower()
        provider_user_id = str(profile.get("id", "")).strip()
        if not email or not provider_user_id:
            raise RuntimeError("google profile missing email or id")
        return OAuthProfile(provider="google", provider_user_id=provider_user_id, email=email)

    if p == "github":
        token = _http_json(
            "POST",
            "https://github.com/login/oauth/access_token",
            form={
                "client_id": _env("FAULTLINE_OAUTH_GITHUB_CLIENT_ID"),
                "client_secret": _env("FAULTLINE_OAUTH_GITHUB_CLIENT_SECRET"),
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        if not isinstance(token, dict):
            raise RuntimeError("github token exchange returned invalid response")
        if token.get("error"):
            raise RuntimeError(
                str(token.get("error_description") or token.get("error") or token)
            )
        access_token = str(token.get("access_token", "")).strip()
        if not access_token:
            raise RuntimeError(f"github token exchange failed: {token}")
        user = _http_json(
            "GET",
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "faultline-cloud",
            },
        )
        if not isinstance(user, dict):
            raise RuntimeError("github profile response invalid")
        provider_user_id = str(user.get("id", "")).strip()
        email = _github_email_from_user(user, access_token)
        if not provider_user_id:
            raise RuntimeError("github profile missing user id")
        if not email:
            raise RuntimeError(
                "github profile missing email — allow user:email scope or set a public email"
            )
        return OAuthProfile(provider="github", provider_user_id=provider_user_id, email=email)

    raise ValueError(f"unsupported oauth provider: {provider}")
