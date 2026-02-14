import argparse
import base64
import secrets
import sys
import time
import webbrowser
from getpass import getpass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from helpers import atomic_write_json, load_json, log_event, utc_now_iso


TWITTER_OAUTH2_TOKEN_URL = "https://api.twitter.com/oauth2/token"
TWITCH_AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize OAuth credentials for Twitter + Twitch and write them to keys.json."
    )
    parser.add_argument("--keys-file", default="configs/keys.json", help="Path to keys JSON file")

    parser.add_argument("--twitter", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--twitter-api-key", default=None)
    parser.add_argument("--twitter-api-secret", default=None)
    parser.add_argument("--twitter-timeout", type=int, default=20)

    parser.add_argument("--twitch", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--twitch-client-id", default=None)
    parser.add_argument("--twitch-client-secret", default=None)
    parser.add_argument("--twitch-redirect-uri", default="http://localhost:8945/twitch/callback")
    parser.add_argument("--twitch-scopes", default="chat:read")
    parser.add_argument("--twitch-timeout", type=int, default=180)
    parser.add_argument("--no-browser", action="store_true")

    return parser.parse_args()


def prompt_bool(question: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"{question} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def prompt_value(label: str, existing: str | None = None, secret: bool = False) -> str:
    if existing:
        return existing
    if secret:
        return getpass(f"{label}: ").strip()
    return input(f"{label}: ").strip()


def load_keys_file(path: str) -> dict[str, Any]:
    return load_json(path, default={})


def save_keys_file(path: str, keys: dict[str, Any]) -> None:
    atomic_write_json(path, keys)


def fetch_twitter_bearer_token(api_key: str, api_secret: str, timeout: int) -> str:
    basic = base64.b64encode(f"{api_key}:{api_secret}".encode("utf-8")).decode("utf-8")
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    }
    data = {"grant_type": "client_credentials"}
    response = requests.post(TWITTER_OAUTH2_TOKEN_URL, headers=headers, data=data, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Twitter response did not include access_token.")
    return token


def build_twitch_authorize_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: list[str],
) -> str:
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{TWITCH_AUTHORIZE_URL}?{urlencode(query)}"


def capture_twitch_oauth_code(redirect_uri: str, expected_state: str, timeout_seconds: int) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http":
        raise ValueError("Twitch redirect URI must use http:// for local callback capture.")

    host = parsed.hostname or "localhost"
    port = parsed.port or 80
    path = parsed.path or "/"
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def do_GET(self) -> None:
            incoming = urlparse(self.path)
            if incoming.path != path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            query = parse_qs(incoming.query)
            state = query.get("state", [""])[0]
            code = query.get("code", [""])[0]
            error = query.get("error", [""])[0]

            if error:
                result["error"] = error
            elif not code:
                result["error"] = "missing_code"
            elif state != expected_state:
                result["error"] = "invalid_state"
            else:
                result["code"] = code

            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"Twitch OAuth received. You can close this tab and return to the terminal."
            )

    server = HTTPServer((host, port), CallbackHandler)
    server.timeout = 1

    deadline = time.time() + max(5, timeout_seconds)
    try:
        while time.time() < deadline and "code" not in result and "error" not in result:
            server.handle_request()
    finally:
        server.server_close()

    if "error" in result:
        raise RuntimeError(f"Twitch OAuth callback error: {result['error']}")
    if "code" not in result:
        raise TimeoutError("Timed out waiting for Twitch OAuth callback.")
    return result["code"]


def exchange_twitch_code_for_token(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    timeout: int,
) -> dict[str, Any]:
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    response = requests.post(TWITCH_TOKEN_URL, data=data, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if "access_token" not in payload:
        raise RuntimeError("Twitch token response did not include access_token.")
    return payload


def fetch_twitch_login(access_token: str, timeout: int) -> str | None:
    headers = {"Authorization": f"OAuth {access_token}"}
    response = requests.get(TWITCH_VALIDATE_URL, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload.get("login")


def init_twitter(args: argparse.Namespace, keys: dict[str, Any]) -> None:
    api_key = prompt_value("Twitter API key", args.twitter_api_key)
    api_secret = prompt_value("Twitter API secret", args.twitter_api_secret, secret=True)
    if not api_key or not api_secret:
        raise ValueError("Twitter API key and secret are required.")

    token = fetch_twitter_bearer_token(api_key, api_secret, timeout=args.twitter_timeout)
    keys["twitter_bearer_token"] = token
    keys["twitter_api_key"] = api_key
    print("Twitter bearer token generated and stored.")


def init_twitch(args: argparse.Namespace, keys: dict[str, Any]) -> None:
    client_id = prompt_value("Twitch client ID", args.twitch_client_id)
    client_secret = prompt_value("Twitch client secret", args.twitch_client_secret, secret=True)
    if not client_id or not client_secret:
        raise ValueError("Twitch client ID and client secret are required.")

    scopes = [scope.strip() for scope in args.twitch_scopes.split(",") if scope.strip()]
    if "chat:read" not in scopes:
        scopes.append("chat:read")

    state = secrets.token_urlsafe(24)
    auth_url = build_twitch_authorize_url(
        client_id=client_id,
        redirect_uri=args.twitch_redirect_uri,
        state=state,
        scopes=scopes,
    )

    print("\nOpen this URL to authorize Twitch chat read access:")
    print(auth_url)
    if not args.no_browser:
        webbrowser.open(auth_url)

    code = capture_twitch_oauth_code(
        redirect_uri=args.twitch_redirect_uri,
        expected_state=state,
        timeout_seconds=args.twitch_timeout,
    )
    token_payload = exchange_twitch_code_for_token(
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=args.twitch_redirect_uri,
        timeout=args.twitch_timeout,
    )

    access_token = token_payload["access_token"]
    login = fetch_twitch_login(access_token, timeout=args.twitch_timeout)

    keys["twitch_oauth_token"] = f"oauth:{access_token}"
    keys["twitch_client_id"] = client_id
    keys["twitch_bot_username"] = login or keys.get("twitch_bot_username", "")
    if token_payload.get("refresh_token"):
        keys["twitch_refresh_token"] = token_payload["refresh_token"]

    print("Twitch OAuth token generated and stored.")
    if login:
        print(f"Twitch bot username set to: {login}")


def main() -> int:
    args = parse_args()
    keys = load_keys_file(args.keys_file)

    do_twitter = args.twitter if args.twitter is not None else prompt_bool("Initialize Twitter token?", True)
    do_twitch = args.twitch if args.twitch is not None else prompt_bool("Initialize Twitch token?", True)

    if not do_twitter and not do_twitch:
        print("Nothing selected. Exiting.")
        return 0

    log_event(
        "oauth_init_started",
        {"keys_file": args.keys_file, "at_utc": utc_now_iso(), "twitter": do_twitter, "twitch": do_twitch},
        "logs/calls/calls.json",
    )

    try:
        if do_twitter:
            init_twitter(args, keys)
        if do_twitch:
            init_twitch(args, keys)

        save_keys_file(args.keys_file, keys)
        log_event(
            "oauth_init_completed",
            {
                "keys_file": args.keys_file,
                "at_utc": utc_now_iso(),
                "twitter": do_twitter,
                "twitch": do_twitch,
            },
            "logs/calls/calls.json",
        )
        print(f"\nSaved credentials to {args.keys_file}")
        return 0

    except Exception as exc:
        log_event(
            "oauth_init_failed",
            {"keys_file": args.keys_file, "error": str(exc)},
            "logs/calls/calls.json",
        )
        print(f"OAuth init failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
