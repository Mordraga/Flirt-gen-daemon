import requests
import json
from collections.abc import Mapping
from typing import Any

from utils.helpers import load_json, load_config, load_keys, log_event
from utils.paths import Paths

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# =============================
# Prompt Templates
# =============================

class _TemplateSafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _normalize_context_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _normalize_context(context: Mapping[str, Any] | None) -> dict[str, str]:
    if not context:
        return {}
    return {
        str(key): _normalize_context_value(value)
        for key, value in context.items()
    }


def _resolve_template_key(keyword: str, registry: Mapping[str, Any]) -> str:
    route = registry.get(keyword, {})
    if isinstance(route, Mapping):
        return str(route.get("prompt_template") or route.get("template") or keyword)
    return keyword


def get_prompt_template(
    keyword: str,
    registry: Mapping[str, Any] | None = None,
    templates: Mapping[str, Any] | None = None,
) -> str | None:
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return None

    registry_data = registry if registry is not None else load_json(Paths.REGISTRY, default={})
    template_data = templates if templates is not None else load_json(Paths.PROMPT_TEMPLATES, default={})

    template_key = _resolve_template_key(keyword, registry_data)
    template_entry = template_data.get(template_key) or template_data.get(keyword)

    if isinstance(template_entry, Mapping):
        template_text = template_entry.get("prompt") or template_entry.get("template")
        if template_text:
            return str(template_text)
        return None

    if isinstance(template_entry, str):
        return template_entry

    return None


def build_prompt_from_keyword(
    keyword: str,
    context: Mapping[str, Any] | None = None,
    registry: Mapping[str, Any] | None = None,
    templates: Mapping[str, Any] | None = None,
) -> str:
    template = get_prompt_template(keyword, registry=registry, templates=templates)
    if not template:
        return (
            f"WARNING: Missing prompt template for keyword '{keyword}' "
            f"in {Paths.PROMPT_TEMPLATES}"
        )

    normalized_context = _normalize_context(context)
    return template.format_map(_TemplateSafeDict(normalized_context)).strip()


# =============================
# OpenRouter Backend
# =============================

def ask_openrouter(prompt: str, spicy: bool = False) -> str:
    config = load_config()
    keys = load_keys()

    mai_config = config.get("Mai-config", config)

    api_key = keys.get("openrouter_api_key")
    if not api_key:
        return f"WARNING: Missing OpenRouter API key in {Paths.KEYS}"

    model = mai_config.get("model", "mistralai/mistral-7b-instruct")
    max_tokens = mai_config.get("max_tokens", 60)
    temp_key = "temperature_spicy" if spicy else "temperature_normal"
    temperature = mai_config.get(temp_key, mai_config.get("temperature_normal", 0.85))
    timeout = mai_config.get("timeout", 30)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "FlirtDaemon",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
        if not r.ok:
            detail = r.text[:500]
            try:
                data = r.json()
                err = data.get("error", {}) if isinstance(data, dict) else {}
                msg = str(err.get("message") or "").strip()
                metadata = err.get("metadata", {}) if isinstance(err, dict) else {}
                raw_payload = metadata.get("raw") if isinstance(metadata, dict) else None

                provider_msg = ""
                if isinstance(raw_payload, str) and raw_payload.strip():
                    try:
                        raw_data = json.loads(raw_payload)
                        provider_msg = str(raw_data.get("error", {}).get("message") or "").strip()
                    except Exception:
                        provider_msg = ""

                bits = [part for part in [msg, provider_msg] if part]
                if bits:
                    detail = " | ".join(bits)
            except ValueError:
                pass

            raise requests.HTTPError(f"{r.status_code} {r.reason}: {detail}", response=r)

        data = r.json()
        return data["choices"][0]["message"]["content"].strip()

    except requests.RequestException as e:
        log_event("openrouter_error", {"error": str(e)}, Paths.ERROR_LOG)
        return f"WARNING: OpenRouter error: {e}"


# =============================
# Unified Entry Point
# =============================

def ask_model(prompt: str, backend: str = "openrouter", spicy: bool = False) -> str:
    if backend == "openrouter":
        return ask_openrouter(prompt, spicy=spicy)
    return "WARNING: No valid backend selected."
