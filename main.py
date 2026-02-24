import sys
import subprocess
from pathlib import Path
from utils.helpers import load_json, log_event
from utils.paths import Paths

if __name__ == "__main__":
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

    # Missing/invalid daemon file
    if not daemon_file or not Path(daemon_file).exists():
        print(f"ERROR: Daemon file not found: {daemon_file}")
        log_event("missing_daemon_file", {
            "keyword": keyword,
            "daemon_file": daemon_file
        }, Paths.ROUTING_ERRORS)
        sys.exit(1)

    # Log the routing
    log_event("route_called", {
        "keyword": keyword,
        "daemon": daemon_file,
        "params": params,
        "username": username
    }, Paths.ROUTING_LOG)

    # Execute daemon - pass through args unchanged
    try:
        result = subprocess.run(
            [sys.executable, daemon_file, params, username],
            cwd=Path.cwd(),
            timeout=60
        )

        # Exit with daemon's exit code
        sys.exit(result.returncode)

    except subprocess.TimeoutExpired:
        print(f"ERROR: Daemon timeout after 60 seconds")
        log_event("daemon_timeout", {
            "keyword": keyword,
            "daemon": daemon_file
        }, Paths.ROUTING_ERRORS)
        sys.exit(1)

    except Exception as e:
        print(f"ERROR: {e}")
        log_event("daemon_execution_error", {
            "keyword": keyword,
            "daemon": daemon_file,
            "error": str(e)
        }, Paths.ROUTING_ERRORS)
        sys.exit(1)