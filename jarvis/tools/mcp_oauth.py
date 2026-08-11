"""OAuth for remote MCP servers — sign in once in a terminal, run headless after.

A remote server (Notion's, Google's, GitHub's) wants proof of *which account*
it is serving. The MCP spec answers with OAuth: the client discovers the
server's authorization endpoints, registers itself, sends the person to a
browser once, and holds tokens from then on. The SDK implements all of that
protocol; this file supplies the two things only Mantrin can decide:

**Where tokens live** — `DATA_DIR/oauth/<name>.json`, mode 0600, one file per
integration. On this machine, owned by this user, deletable with `rm` — the
same story as every other secret here.

**Where the browser is** — nowhere, usually. The daemon runs headless at
login; it must never sit waiting on a consent screen no one can see (a
Spotify server once held the whole brain hostage doing exactly that). So the
interactive dance is allowed only inside `mantrin connect <name>`, where a
human and a browser are present. The daemon gets a provider that uses stored
tokens, refreshes them silently, and *fails* if asked to start from scratch.
"""

from __future__ import annotations

import asyncio
import threading
import time
import urllib.parse
import webbrowser

from .. import config

# Not 8080: Spotify's redirect already lives there, and a port collision
# during sign-in is a miserable thing to debug (we know; we debugged it).
_PORT = 8976
REDIRECT_URI = f"http://127.0.0.1:{_PORT}/callback"
_AUTH_TIMEOUT_S = 300


def token_file(name: str):
    return config.DATA_DIR / "oauth" / f"{name}.json"


def signed_in(name: str) -> bool:
    """Tokens on disk — not merely the file: a pre-seeded client
    registration (Google's flow) creates the file before any sign-in."""
    import json

    try:
        return "tokens" in json.loads(token_file(name).read_text() or "{}")
    except (OSError, ValueError):
        return False


def sign_out(name: str) -> None:
    token_file(name).unlink(missing_ok=True)


class _FileStorage:
    """The SDK's TokenStorage protocol, backed by one 0600 JSON file that
    holds both the tokens and the client registration (so the server
    remembers us across restarts instead of re-registering forever)."""

    def __init__(self, name: str):
        self._path = token_file(name)

    def _read(self) -> dict:
        import json

        try:
            return json.loads(self._path.read_text() or "{}")
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> None:
        import json

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2))
        self._path.chmod(0o600)

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken

        raw = self._read().get("tokens")
        return OAuthToken.model_validate(raw) if raw else None

    async def set_tokens(self, tokens) -> None:
        data = self._read()
        data["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        self._write(data)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull

        raw = self._read().get("client")
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def set_client_info(self, info) -> None:
        data = self._read()
        data["client"] = info.model_dump(mode="json", exclude_none=True)
        self._write(data)


class _Callback:
    """One-shot localhost listener for the browser's return trip.

    Started *before* the browser opens (redirect_handler runs first), torn
    down the moment the code arrives. Runs its own thread + loop because the
    SDK calls us from inside the transport's loop, which must stay free to
    make the token request afterwards.
    """

    def __init__(self):
        self.result: dict = {}
        self._got = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._serve, daemon=True, name="oauth-callback").start()

    def _serve(self) -> None:
        import http.server

        holder = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):                            # noqa: N802 — stdlib API
                query = urllib.parse.urlparse(self.path).query
                params = urllib.parse.parse_qs(query)
                holder.result = {k: v[0] for k, v in params.items()}
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    "<h2>Mantrin connected — you can close this tab.</h2>".encode()
                )
                holder._got.set()

            def log_message(self, *args):                # silence request logging
                pass

        with http.server.HTTPServer(("127.0.0.1", _PORT), Handler) as server:
            server.timeout = 1.0
            deadline = time.monotonic() + _AUTH_TIMEOUT_S
            while not self._got.is_set() and time.monotonic() < deadline:
                server.handle_request()

    def wait(self) -> dict:
        self._got.wait(timeout=_AUTH_TIMEOUT_S)
        return self.result


_patched = False


def _tolerate_trailing_slash() -> None:
    """Google says its issuer is accounts.google.com in one document and
    accounts.google.com/ in the other; the SDK compares the strings exactly
    and refuses the world's largest identity provider over one character.
    Soften just that check: identical-but-for-the-trailing-slash passes."""
    global _patched
    if _patched:
        return
    _patched = True
    from mcp.client.auth import oauth2

    strict = oauth2.validate_metadata_issuer

    def lenient(metadata, expected):
        try:
            strict(metadata, expected)
        except Exception:
            issuer = str(getattr(metadata, "issuer", "")).rstrip("/")
            if issuer and issuer == str(expected).rstrip("/"):
                return
            raise

    oauth2.validate_metadata_issuer = lenient


def build(name: str, url: str, *, interactive: bool,
          client_id: str | None = None, client_secret: str | None = None,
          scope: str | None = None):
    """An httpx auth object for this server — the SDK does the protocol.

    Servers that support Dynamic Client Registration (Notion, GitHub) need
    nothing else. Google's authorization server returns 404 for /register —
    it only speaks to pre-registered clients — so for Google the caller
    passes the client_id/secret of the user's own Desktop OAuth client, and
    seeding it into storage makes the SDK skip registration entirely.
    """
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    _tolerate_trailing_slash()

    auth_method = "client_secret_post" if client_secret else "none"
    metadata = OAuthClientMetadata(
        client_name="Mantrin",
        client_uri="https://tryjarvis.in",
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method=auth_method,         # PKCE either way
        # Without this the SDK requests every scope the server advertises —
        # which for Gmail includes gmail.metadata, a scope that FORBIDS
        # search queries and poisons the whole token even alongside broader
        # grants ("The caller does not have permission", found the hard way).
        scope=scope,
    )

    storage = _FileStorage(name)
    if client_id:
        from mcp.shared.auth import OAuthClientInformationFull

        info = OAuthClientInformationFull(
            client_id=client_id, client_secret=client_secret,
            **metadata.model_dump(mode="json", exclude_none=True),
        )
        data = storage._read()
        data["client"] = info.model_dump(mode="json", exclude_none=True)
        storage._write(data)

    callback = _Callback()

    async def open_browser(auth_url: str) -> None:
        callback.start()
        print(f"\n  Opening the sign-in page…\n  (if no browser appears: {auth_url})",
              flush=True)
        webbrowser.open(auth_url)

    async def wait_for_code():
        from mcp.client.auth import AuthorizationCodeResult

        got = await asyncio.to_thread(callback.wait)
        if "code" not in got:
            raise RuntimeError("the sign-in page never came back (5 min)")
        return AuthorizationCodeResult(code=got["code"], state=got.get("state"),
                                       iss=got.get("iss"))

    async def refuse(_url: str) -> None:
        raise RuntimeError(
            f"'{name}' needs a browser sign-in, and a headless daemon has no "
            f"browser. Run: mantrin connect {name}"
        )

    async def never():
        raise RuntimeError(f"sign in first: mantrin connect {name}")

    return OAuthClientProvider(
        server_url=url,
        client_metadata=metadata,
        storage=storage,
        redirect_handler=open_browser if interactive else refuse,
        callback_handler=wait_for_code if interactive else never,
    )
