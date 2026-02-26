import sys
import subprocess
from pathlib import Path
from utils.helpers import load_json, log_event, resolve_existing_path
from utils.paths import Paths


def _build_daemon_command(daemon_file: str, params: str, username: str) -> list[str]:
    if getattr(sys, "frozen", False):
        # In packaged mode, re-enter the executable in script-runner mode.
        return [sys.executable, "--run-script", daemon_file, params, username]
    return [sys.executable, daemon_file, params, username]

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Usage: python main.py <keyword> <params> [username]
    if len(sys.argv) < 3:
        print("Usage: python main.py <keyword> <params> [username]")
        sys.exit(1)
    
    keyword = sys.argv[1].lower()
    params = sys.argv[2]
    username = sys.argv[3] if len(sys.argv) >= 4 else "Anonymous"
    
    # Load registry
    registry = load_json(Paths.REGISTRY, default={})
    route = registry.get(keyword)

    # Unknown keyword
    if not route:
        print(f"ERROR: Unknown keyword '{keyword}'")
        log_event("unknown_keyword", {
            "keyword": keyword,
            "username": username,
            "params": params
        }, Paths.ROUTING_ERRORS)
        sys.exit(1)

    daemon_file = route.get("file")
    daemon_path = resolve_existing_path(daemon_file) if daemon_file else Path("")

    # Missing/invalid daemon file
    if not daemon_file or not daemon_path.exists():
        print(f"ERROR: Daemon file not found: {daemon_file}")
        log_event("missing_daemon_file", {
            "keyword": keyword,
            "daemon_file": daemon_file
        }, Paths.ROUTING_ERRORS)
        sys.exit(1)

    # Log the routing
    log_event("route_called", {
        "keyword": keyword,
        "daemon": str(daemon_path),
        "params": params,
        "username": username
    }, Paths.ROUTING_LOG)

    # Execute daemon - pass through args unchanged
    try:
        command = _build_daemon_command(str(daemon_path), params, username)
        result = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parent,
            timeout=60,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")

        # Exit with daemon's exit code
        sys.exit(result.returncode)

    except subprocess.TimeoutExpired:
        print(f"ERROR: Daemon timeout after 60 seconds")
        log_event("daemon_timeout", {
            "keyword": keyword,
            "daemon": str(daemon_path)
        }, Paths.ROUTING_ERRORS)
        sys.exit(1)

    except Exception as e:
        print(f"ERROR: {e}")
        log_event("daemon_execution_error", {
            "keyword": keyword,
            "daemon": str(daemon_path),
            "error": str(e)
        }, Paths.ROUTING_ERRORS)
        sys.exit(1)
