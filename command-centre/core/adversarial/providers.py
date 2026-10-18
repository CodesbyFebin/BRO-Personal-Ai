"""Small, explicit cloud and local model provider clients.

No provider is contacted unless it is configured. API keys are referenced by
environment variable name and are never stored in provider configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}$")
_ENV = re.compile(r"^[A-Z_][A-Z0-9_]{1,79}$")


def _is_local_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    if host in {"localhost", "host.docker.internal"} or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        try:
            addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError:
            return False
        return bool(addresses) and all(
            ipaddress.ip_address(item[4][0]).is_private or ipaddress.ip_address(item[4][0]).is_loopback
            for item in addresses
        )


@dataclass(frozen=True)
class ModelProvider:
    id: str
    protocol: str
    model: str
    base_url: str
    trust_domain: str = "local"
    weight: float = 1.0
    api_key_env: str | None = None
    timeout_seconds: int = 60

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.protocol, self.base_url.rstrip("/"), self.model)

    def public_view(self) -> dict:
        key_available = not self.api_key_env or bool(os.environ.get(self.api_key_env, ""))
        return {"id": self.id, "protocol": self.protocol, "model": self.model,
                "trust_domain": self.trust_domain, "weight": self.weight,
                "ready": key_available, "key_required": bool(self.api_key_env)}

    def complete(self, system: str, user: str, structured: bool = True) -> str:
        api_key = os.environ.get(self.api_key_env, "") if self.api_key_env else ""
        if self.api_key_env and not api_key:
            raise RuntimeError("provider_key_unavailable")
        if self.protocol == "ollama":
            url = self.base_url
            payload = {"model": self.model, "stream": False, "format": "json",
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        elif self.protocol == "anthropic":
            url = self.base_url.rstrip("/")
            if not url.endswith("/messages"):
                url += "/messages"
            payload = {"model": self.model, "max_tokens": 1800, "system": system,
                       "messages": [{"role": "user", "content": user}]}
        elif self.protocol == "gemini":
            url = self.base_url.rstrip("/")
            if ":generateContent" not in url:
                url += f"/models/{self.model}:generateContent"
            payload = {"systemInstruction": {"parts": [{"text": system}]},
                       "contents": [{"role": "user", "parts": [{"text": user}]}],
                       "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1800}}
        else:
            url = self.base_url
            if url.endswith("/v1"):
                url += "/chat/completions"
            elif not url.endswith("/chat/completions"):
                url = url.rstrip("/") + "/v1/chat/completions"
            payload = {"model": self.model, "temperature": 0.1,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if structured:
                payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.protocol == "anthropic":
            headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        elif self.protocol == "gemini":
            headers["x-goog-api-key"] = api_key
        elif api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read(2_000_000))
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("provider_request_failed") from exc
        if self.protocol == "ollama":
            content = data.get("message", {}).get("content", "")
        elif self.protocol == "anthropic":
            content = "\n".join(part.get("text", "") for part in data.get("content", []) if isinstance(part, dict))
        elif self.protocol == "gemini":
            parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            content = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict))
        else:
            choices = data.get("choices") or []
            content = choices[0].get("message", {}).get("content", "") if choices else ""
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("provider_empty_response")
        return content.strip()


def _parse_provider(item: object) -> ModelProvider:
    if not isinstance(item, dict):
        raise ValueError("each provider must be a JSON object")
    provider_id = item.get("id")
    protocol = item.get("protocol", "openai")
    model = item.get("model")
    base_url = item.get("base_url")
    trust = item.get("trust_domain", "local")
    if not isinstance(provider_id, str) or not _ID.fullmatch(provider_id):
        raise ValueError("provider id must contain only letters, digits, _ or -")
    if protocol not in {"ollama", "openai", "anthropic", "gemini"}:
        raise ValueError(f"unsupported protocol for provider {provider_id}")
    if not isinstance(model, str) or not model.strip() or len(model) > 160:
        raise ValueError(f"provider {provider_id} needs a model name")
    if not isinstance(base_url, str) or len(base_url) > 512:
        raise ValueError(f"provider {provider_id} needs a valid base_url")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"provider {provider_id} base_url must be an HTTP(S) URL without credentials or query parameters")
    if trust not in {"local", "remote"}:
        raise ValueError(f"provider {provider_id} trust_domain must be local or remote")
    if trust == "local" and not _is_local_host(parsed.hostname):
        raise ValueError(f"provider {provider_id} uses a public host; set trust_domain=remote to explicitly allow data egress")
    key_env = item.get("api_key_env")
    if key_env is not None and (not isinstance(key_env, str) or not _ENV.fullmatch(key_env)):
        raise ValueError(f"provider {provider_id} api_key_env must be an environment-variable name")
    try:
        weight = float(item.get("weight", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"provider {provider_id} weight must be numeric") from exc
    if not 0.1 <= weight <= 3.0:
        raise ValueError(f"provider {provider_id} weight must be between 0.1 and 3")
    timeout = item.get("timeout_seconds", 60)
    if not isinstance(timeout, int) or not 3 <= timeout <= 120:
        raise ValueError(f"provider {provider_id} timeout_seconds must be between 3 and 120")
    base_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    return ModelProvider(provider_id, protocol, model.strip(), base_url, trust, weight, key_env, timeout)


def load_providers(raw: str | None = None, ollama_model: str = "", ollama_url: str = "") -> tuple[ModelProvider, ...]:
    raw = os.environ.get("BRO_DEBATE_PROVIDERS", "") if raw is None else raw
    if raw.strip():
        try:
            records = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("BRO_DEBATE_PROVIDERS must be a JSON array") from exc
        if not isinstance(records, list) or len(records) > 5:
            raise ValueError("BRO_DEBATE_PROVIDERS must be an array with at most five providers")
        providers = tuple(_parse_provider(record) for record in records)
    elif ollama_model:
        providers = (_parse_provider({"id": "ollama-local", "protocol": "ollama", "model": ollama_model,
                                     "base_url": ollama_url, "trust_domain": "local"}),)
    else:
        providers = ()
    seen: set[tuple[str, str, str]] = set()
    for provider in providers:
        if provider.identity in seen:
            raise ValueError("duplicate endpoint/model entries cannot count as independent reviewers")
        seen.add(provider.identity)
    return providers


def load_models(raw: str | None = None, ollama_model: str = "", ollama_url: str = "") -> tuple[ModelProvider, ...]:
    """Load selectable inference models from BRO_MODELS and optional Ollama."""
    raw = os.environ.get("BRO_MODELS", "") if raw is None else raw
    records: list[object] = []
    if raw.strip():
        try:
            records = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("BRO_MODELS must be a JSON array") from exc
        if not isinstance(records, list) or len(records) > 50:
            raise ValueError("BRO_MODELS must be an array with at most 50 models")
    providers = [_parse_provider(record) for record in records]
    if ollama_model and not any(p.id == "ollama-local" for p in providers):
        providers.append(_parse_provider({"id": "ollama-local", "protocol": "ollama", "model": ollama_model,
                                          "base_url": ollama_url, "trust_domain": "local"}))
    ids = [provider.id for provider in providers]
    if len(ids) != len(set(ids)):
        raise ValueError("BRO_MODELS model ids must be unique")
    return tuple(providers)
