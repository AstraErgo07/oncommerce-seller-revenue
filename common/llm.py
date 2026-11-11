"""
common/llm.py - the ONE place both agents talk to an LLM.

call_llm(prompt) is the only provider-specific function. To swap provider
(Anthropic, Azure, Gemini, a local model...) edit just this function.

Environment variables (ASSUMPTION: an OpenAI-compatible chat-completions API):
  OPENAI_API_KEY   - API key. If NOT set, call_llm raises LLMUnavailable and each
                     agent falls back to its rules-based explanation.
  OPENAI_BASE_URL  - optional, default https://api.openai.com/v1
  AGENT_MODEL      - optional, default gpt-4o-mini
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


class LLMUnavailable(Exception):
    """No key set, or the provider call failed. Callers fall back to rules."""


def call_llm(prompt: str) -> str:
    """Send prompt to the LLM and return its raw text reply."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise LLMUnavailable("No OPENAI_API_KEY set - using rules-based explanation")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("AGENT_MODEL", "gpt-4o-mini")
    body = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "You are a careful UK marketplace analyst. Reply with JSON only."},
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as e:
        raise LLMUnavailable(f"LLM call failed: {e}") from e


def as_text(value) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value).strip()


def extract_json_object(text: str) -> dict:
    """Strip code fences and return the first {...} object. Raises ValueError."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty reply")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    return data


def validate_common(data: dict, required: list[str], allowed: dict[str, list[str]]) -> dict:
    """Check required keys exist and enumerated fields hold allowed values (case-insensitive).
    Returns a cleaned copy with text fields stringified. Raises ValueError."""
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"missing keys: {missing}")
    out = {}
    for k in required:
        v = as_text(data[k])
        if k in allowed:
            match = {a.lower(): a for a in allowed[k]}.get(v.lower())
            if match is None:
                raise ValueError(f"invalid {k}: {data[k]!r}")
            v = match
        if not v:
            raise ValueError(f"empty {k}")
        out[k] = v
    return out
