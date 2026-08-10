"""`mantrin connect spotify` — plug an integration in without reading docs.

Every integration is an MCP server: a block in mcp.json plus a key in the
environment. That is a good architecture and a bad first-run experience —
"copy this JSON, export that variable, restart" is three chances to stop
being interested. This command walks the whole path in one place:

    seed the block  →  open the page where the key lives  →  take the key
    (hidden input, saved 0600)  →  restart  →  say whether it actually works

The one thing it never pretends to do is create the key itself. Keys come
from *your* accounts — Spotify's dashboard, Google's console — behind your
login. Mantrin takes you to the right page and takes the paste; the click
in the middle is yours, and should be.

Verification reads the daemon's own startup lines, because those already
tell the truth: `(MCP 'spotify': 5 tools)` is connected, "off — set X" is
waiting, "failed to start" is broken. No second status system to disagree
with the first.
"""

from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config

_EXAMPLE = Path(__file__).resolve().parent / "assets" / "mcp.example.json"


@dataclass
class Key:
    env: str
    label: str
    path: bool = False              # a file path, not a secret — visible input


@dataclass
class Spec:
    name: str
    what: str                       # what you can say once it works
    docs: str = ""                  # the page where the key is created
    steps: tuple[str, ...] = ()     # what to do on that page
    keys: tuple[Key, ...] = ()
    needs: tuple[str, ...] = ()     # binaries the server runs on
    mcp: bool = True                # False → keys only, no mcp.json block


REGISTRY: dict[str, Spec] = {
    "whatsapp": Spec(
        "whatsapp", '"what did Ria send?", "reply that I\'m on my way"',
        steps=("A QR code will appear below.",
               "Phone → WhatsApp → Settings → Linked devices → Link a device.",
               "Scan it, wait for 'connected', then press Ctrl+C."),
        needs=("npx",),
    ),
    "slack": Spec(
        "slack", '"anything for me in #general?"',
        docs="https://api.slack.com/apps",
        steps=("Create an app (or open yours) → OAuth & Permissions.",
               "Add the scopes you want it to have, install to workspace.",
               "Copy the user OAuth token (starts with xoxp-)."),
        keys=(Key("SLACK_XOXP_TOKEN", "Slack user OAuth token"),),
        needs=("npx",),
    ),
    "google-calendar": Spec(
        "google-calendar", '"what\'s on today?", "block Thursday 4pm with Ria"',
        docs="https://console.cloud.google.com/apis/credentials",
        steps=("Create/select a project and enable the Google Calendar API.",
               "Credentials → Create credentials → OAuth client ID → Desktop app.",
               "Download the client JSON — that file is what Mantrin needs."),
        keys=(Key("GOOGLE_OAUTH_CREDENTIALS", "path to the downloaded OAuth JSON", path=True),),
        needs=("npx",),
    ),
    "gmail": Spec(
        "gmail", '"anything important in my inbox?"',
        docs="https://console.cloud.google.com/apis/credentials",
        steps=("Uses the same OAuth client as Calendar — enable the Gmail API on it too.",
               "If you already connected Calendar, just point at the same JSON."),
        keys=(Key("_GMAIL_OAUTH_JSON", "path to the OAuth client JSON", path=True),),
        needs=("npx",),
    ),
    "notion": Spec(
        "notion", '"add this to my ideas page"',
        docs="https://www.notion.so/profile/integrations",
        steps=("Create an internal integration and copy its secret.",
               "In Notion, share the pages it should see: page ⋯ → Connections."),
        keys=(Key("NOTION_TOKEN", "Notion integration secret"),),
        needs=("npx",),
    ),
    "github": Spec(
        "github", '"any reviews waiting on me?", "what broke in CI?"',
        docs="https://github.com/settings/personal-access-tokens",
        steps=("Create a fine-grained personal access token",
               "scoped to the repos you care about."),
        keys=(Key("GITHUB_PAT", "GitHub personal access token"),),
        needs=("docker",),
    ),
    "home-assistant": Spec(
        "home-assistant", '"turn off the bedroom lights"',
        docs="https://my.home-assistant.io/redirect/profile/",
        steps=("In Home Assistant: Settings → Devices & services → Add integration",
               "→ Model Context Protocol Server (once).",
               "Then in your profile, create a long-lived access token."),
        keys=(Key("HASS_TOKEN", "Home Assistant long-lived token"),),
        needs=("uvx",),
    ),
    "spotify": Spec(
        "spotify", '"put on something quiet", "skip this one"',
        docs="https://developer.spotify.com/dashboard",
        steps=("Create an app. Redirect URI must be exactly:",
               "  http://127.0.0.1:8080/callback",
               "Copy the Client ID and Client Secret. (Playback needs Premium.)"),
        keys=(Key("SPOTIFY_CLIENT_ID", "Spotify client ID"),
              Key("SPOTIFY_CLIENT_SECRET", "Spotify client secret")),
        needs=("uvx",),
    ),
    "weather": Spec(
        "weather", '"do I need an umbrella?"',
        steps=("Open-Meteo is free — no key, no account. Nothing to do.",),
        needs=("uvx",),
    ),
    "google-maps": Spec(
        "google-maps", '"how long to the airport right now?"',
        docs="https://console.cloud.google.com/apis/credentials",
        steps=("In a Google Cloud project, enable the Places, Directions and",
               "Distance Matrix APIs, then create an API key."),
        keys=(Key("GOOGLE_MAPS_API_KEY", "Google Maps API key"),),
        needs=("npx",),
    ),
    "x": Spec(
        "x", '"post this", "any replies to my last post?"',
        docs="https://developer.x.com/en/portal/dashboard",
        steps=("Create a project + app (free tier works).",
               "App settings → user authentication: read & write.",
               "Keys & tokens → generate all four below."),
        keys=(Key("X_API_KEY", "API key"),
              Key("X_API_SECRET", "API key secret"),
              Key("X_ACCESS_TOKEN", "access token"),
              Key("X_ACCESS_SECRET", "access token secret")),
        mcp=False,
    ),
}


# ------------------------------------------------------------- the pieces

def _example_block(name: str) -> dict | None:
    data = json.loads(_EXAMPLE.read_text())
    for server in data.get("servers", []):
        if server.get("name") == name:
            return server
    return None


def _mcp_config() -> dict:
    if config.MCP_CONFIG_FILE.exists():
        try:
            return json.loads(config.MCP_CONFIG_FILE.read_text() or "{}")
        except json.JSONDecodeError:
            print(f"  ({config.MCP_CONFIG_FILE} is not valid JSON — fix it first)")
            raise SystemExit(1)
    return {"servers": []}


def _seed_block(name: str) -> None:
    """Put the integration's block into the live mcp.json, once."""
    data = _mcp_config()
    servers = data.setdefault("servers", [])
    if any(s.get("name") == name for s in servers):
        return                          # already there — keys are the question
    block = _example_block(name)
    if block is None:
        raise SystemExit(f"No template for '{name}'.")
    servers.append(block)
    config.MCP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.MCP_CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  Added the {name} block to {config.MCP_CONFIG_FILE}.")


def _open_page(url: str) -> None:
    print(f"\n  Get it here: {url}")
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def _ask_keys(spec: Spec) -> dict[str, str] | None:
    """Collect the spec's keys. Hidden input for secrets, visible for paths.
    Returns None if the user bailed (blank on a required key)."""
    settings = config.load_settings()
    saved = settings.get("keys") or {}
    got: dict[str, str] = {}
    for key in spec.keys:
        current = os.environ.get(key.env) or saved.get(key.env)
        if current:
            answer = input(f"  {key.env} is already set. Replace it? [n] ").strip().lower()
            if answer not in ("y", "yes"):
                got[key.env] = str(current)
                continue
        while True:
            if key.path:
                raw = input(f"  {key.label}: ").strip()
                if not raw:
                    return None
                path = Path(raw).expanduser()
                if path.exists():
                    got[key.env] = str(path.resolve())
                    break
                print(f"  ({path} doesn't exist — check the download location)")
            else:
                raw = getpass.getpass(f"  {key.label} (hidden, blank to cancel): ").strip()
                if not raw:
                    return None
                got[key.env] = raw
                break
    # Persist everything except private markers (keys starting with _ are
    # flow inputs, not environment the daemon needs).
    to_save = {k: v for k, v in got.items() if not k.startswith("_")}
    if to_save:
        saved.update(to_save)
        settings["keys"] = saved
        config.save_settings(settings)
        os.environ.update(to_save)
        print(f"  Saved to {config.CONFIG_FILE} (readable only by you).")
    return got


def _check_needs(spec: Spec) -> bool:
    hints = {"npx": "install Node.js (nodejs.org)",
             "uvx": "install uv (docs.astral.sh/uv)",
             "docker": "install Docker (docs.docker.com)"}
    for binary in spec.needs:
        if not shutil.which(binary):
            print(f"  This one runs on `{binary}`, which isn't installed — "
                  f"{hints.get(binary, 'install it')} and re-run.")
            return False
    return True


# ------------------------------------------------- special first-run flows

def _pair_whatsapp() -> None:
    """The bridge pairs by QR, interactively, once. State lands in the same
    directory the daemon's block points at, so pairing here IS pairing there."""
    env = dict(os.environ)
    block = _example_block("whatsapp") or {}
    for k, v in (block.get("env") or {}).items():
        env[k] = os.path.expandvars(v)
    print()
    try:
        subprocess.run(["npx", "-y", "mantrin-whatsapp@latest"], env=env)
    except KeyboardInterrupt:
        pass                            # Ctrl+C after scanning is the happy path
    print()


def _auth_gmail(oauth_json: str) -> bool:
    """Gmail's server keeps its own credentials in ~/.gmail-mcp — copy the
    OAuth client there and run its one-time browser sign-in."""
    keys_dir = Path.home() / ".gmail-mcp"
    keys_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(oauth_json, keys_dir / "gcp-oauth.keys.json")
    print("\n  A browser will open for the one-time Google sign-in…")
    result = subprocess.run(["npx", "-y", "@gongrzhe/server-gmail-autoauth-mcp", "auth"])
    return result.returncode == 0


# ----------------------------------------------------------- verification

def _daemon_reports(name: str) -> str | None:
    """The daemon's latest word on this server, from its own logs."""
    from . import service

    if service.installed():
        out = subprocess.run(
            ["journalctl", "--user", "-u", service.UNIT, "-n", "300", "--no-pager"],
            capture_output=True, text=True).stdout
    else:
        log = config.DATA_DIR / "daemon.log"
        out = log.read_text()[-20_000:] if log.exists() else ""
    lines = [l for l in out.splitlines() if f"'{name}'" in l]
    return lines[-1] if lines else None


def _verdict(name: str) -> None:
    report = _daemon_reports(name)
    spec = REGISTRY[name]
    if report and ": " in report and "tools)" in report:
        tools = report.rsplit(":", 1)[-1].strip(" ()\n")
        print(f"\nConnected — {name} is live ({tools}). Try: {spec.what}")
    elif report and "off — set" in report:
        print(f"\nStill waiting: {report[report.index('('):].strip()}")
    elif report:
        print(f"\nIt didn't come up cleanly: {report.strip()}")
        print("`mantrin logs` has the full story.")
    else:
        print("\nNo word from the daemon about it yet — `mantrin logs` to watch.")


# ------------------------------------------------------------- the command

def connect(name: str | None) -> int:
    try:
        return _connect(name)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1


def _connect(name: str | None) -> int:
    if not name:
        return _list()
    name = name.lower().strip()
    if name not in REGISTRY:
        near = [n for n in REGISTRY if name in n]
        if len(near) == 1:
            name = near[0]
        else:
            print(f"Don't know '{name}'. Available: {', '.join(REGISTRY)}")
            return 1
    spec = REGISTRY[name]

    print(f"Connecting {name} — {spec.what}")
    if not _check_needs(spec):
        return 1
    if spec.mcp:
        _seed_block(name)
    if spec.docs:
        _open_page(spec.docs)
    if spec.steps:
        print()
        for step in spec.steps:
            print(f"  {step}")
    print()

    got = _ask_keys(spec)
    if got is None and spec.keys:
        print("Nothing saved — run `mantrin connect {0}` again any time.".format(name))
        return 1

    if name == "gmail":
        if not _auth_gmail(got["_GMAIL_OAUTH_JSON"]):
            print("The Google sign-in didn't finish — re-run to try again.")
            return 1
    if name == "whatsapp":
        _pair_whatsapp()

    from . import service

    print("Restarting Mantrin so it picks this up…")
    service.restart()
    if spec.mcp:
        _verdict(name)
    else:
        print(f"\nKeys saved. Try: {spec.what}")
    return 0


def _list() -> int:
    """`mantrin connect` bare: what exists, and where each one stands."""
    live = {s.get("name") for s in _mcp_config().get("servers", [])}
    print("Integrations — `mantrin connect <name>` walks you through any of them:\n")
    for name, spec in REGISTRY.items():
        if not spec.mcp:
            state = "connected" if config.x_configured() else "not connected"
        elif name not in live:
            state = "not connected"
        else:
            report = _daemon_reports(name) or ""
            if "tools)" in report:
                state = "connected"
            elif "off — set" in report:
                state = "waiting for its key"
            elif "failed" in report:
                state = "failing — `mantrin logs`"
            else:
                state = "configured"
        print(f"  {name:16} {state:22} {spec.what}")
    print("\nAnything else that speaks MCP: add a block to "
          f"{config.MCP_CONFIG_FILE} (see jarvis/assets/mcp.example.json).")
    return 0
