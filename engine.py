import json
import requests
from pathlib import Path

SPICE_FILE = Path("spice.json")
THEME_FILE = Path("themes.json")


OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"


def load_spice_levels():
    """Read spice level descriptions from JSON."""
    with open(SPICE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_themes():
    with open(THEME_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def clamp_level(level: int) -> int:
    """Keep level between 1 and 10."""
    return max(1, min(level, 10))


def build_prompt(theme: str, style: str, level: int, spice_data: dict, theme_data: dict) -> str:
    lvl = str(clamp_level(level))
    spice_desc = spice_data.get(lvl, "playful and flirty energy")

    theme_key = theme.strip().lower()
    anchors = theme_data.get(theme_key, [])

    if anchors:
        enriched_theme = f"{theme_key} (include references to: {', '.join(anchors)})"
    else:
        enriched_theme = theme_key or "general charm"

    return f"""
You generate sharp, original flirt lines for live chat.

Constraints:
- One single sentence.
- Avoid generic compliments.
- Be specific to the theme.
- Twitch-safe.
- Clever and memorable.

Style: {style}
Theme: {enriched_theme}
Energy: {spice_desc}

Generate one line.
""".strip()

def ask_ollama(prompt: str, model: str = "dolphin3:8b") -> str:
    """Send prompt to Ollama and stream the response until done.

    Supports both /api/chat (yields token deltas under message.content)
    and /api/generate (yields token deltas under response).
    """

    def _stream(url: str, payload: dict) -> str:
        with requests.post(url, json=payload, stream=True, timeout=120) as r:
            try:
                r.raise_for_status()
            except requests.HTTPError:
                _ = r.content  # load body so callers can read it
                raise
            collected = []
            for line in r.iter_lines():
                if not line:
                    continue
                data = json.loads(line.decode("utf-8"))
                # /api/generate streaming shape
                if "response" in data and isinstance(data.get("response"), str):
                    collected.append(data["response"])
                # /api/chat streaming shape
                elif isinstance(data.get("message"), dict):
                    content = data["message"].get("content")
                    if isinstance(content, str):
                        collected.append(content)
                if data.get("done"):
                    break
            return "".join(collected).strip()

    def _response_message(response) -> str:
        body = response.content or b""

        if body:
            try:
                data = json.loads(body.decode("utf-8"))
            except (ValueError, json.JSONDecodeError):
                data = None
            else:
                if isinstance(data, dict):
                    message = data.get("error") or data.get("message")
                    if isinstance(message, str):
                        return message.strip()

        if not body:
            return ""

        return body.decode("utf-8", errors="ignore").strip()

    def _format_http_error(http_err: requests.HTTPError) -> str:
        response = http_err.response
        if response is not None:
            message = _response_message(response)
            if response.status_code == 404 and "model" in message.lower() and "not found" in message.lower():
                return f"WARNING: Ollama model '{model}' not found. Run `ollama pull {model}` and try again."
            if message:
                return f"WARNING: Ollama error {response.status_code}: {message}"
            return f"WARNING: Ollama error {response.status_code}"
        return f"WARNING: Error contacting Ollama: {http_err}"

    chat_payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "options": {
            "num_predict": 40,
            "temperature": 0.9,
            "top_p": 0.95
        }
    }

    try:
        return _stream(OLLAMA_CHAT_URL, chat_payload)
    except requests.HTTPError as http_err:
        if http_err.response is not None and http_err.response.status_code == 404:
            generate_payload = {"model": model, "prompt": prompt}
            try:
                return _stream(OLLAMA_GENERATE_URL, generate_payload)
            except requests.HTTPError as fallback_http_err:
                return _format_http_error(fallback_http_err)
            except requests.RequestException as fallback_err:
                return f"WARNING: Error contacting Ollama: {fallback_err}"
        return _format_http_error(http_err)
    except requests.RequestException as err:
        return f"WARNING: Error contacting Ollama: {err}"
