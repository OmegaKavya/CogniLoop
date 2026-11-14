"""
Shared language-model client.

Why this exists
---------------
Quiz generation and quiz evaluation each grew their own provider plumbing, and
they diverged. Generation gained a Groq path and an `OLLAMA_ENABLED` gate;
evaluation never did. Since production runs on Groq with no Ollama deployed,
evaluation's only provider was unreachable there, so AI grading silently never
ran and every learner received the canned fallback feedback. The unreachable
call was not free either: a refused connection to localhost cost about eight
seconds per submission, and an unreachable remote host cost the full timeout.

One client, used by both call sites, keeps provider selection, gating and
timeouts in a single place where they can be reasoned about and tested.

Providers are tried in order of cost to the learner: Groq first because it is
fast and reachable from a deployment, Ollama second because it is local and
slow. A provider that is not configured is skipped rather than attempted, so a
missing key or a disabled Ollama costs nothing instead of a timeout.
"""

import json

import requests

from backend import config


class LLMUnavailable(Exception):
    """No provider is configured, or every configured provider failed."""


def _extract_json(text):
    """Parse a JSON object or array from a model response.

    Models occasionally wrap JSON in prose or a fenced block despite being asked
    not to, so fall back to the outermost bracketed span before giving up.
    """
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if len(text.split("```")) > 1 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    try:
        return json.loads(text)
    except ValueError:
        pass
    # Try whichever delimiter opens first, so that an array wrapped in prose is
    # not mistaken for the first object nested inside it.
    spans = []
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            spans.append((start, text[start:end + 1]))

    for _, span in sorted(spans):
        try:
            return json.loads(span)
        except ValueError:
            continue
    return None


class LLMClient:
    """Requests JSON completions from whichever provider is available."""

    def __init__(self, groq_api_key=None, groq_url=None, groq_model=None,
                 ollama_url=None, ollama_model=None, ollama_enabled=None,
                 groq_timeout=None, ollama_timeout=None):
        self.groq_api_key = config.GROQ_API_KEY if groq_api_key is None else groq_api_key
        self.groq_url = groq_url or config.GROQ_URL
        self.groq_model = groq_model or config.GROQ_MODEL
        self.groq_timeout = config.GROQ_TIMEOUT if groq_timeout is None else groq_timeout

        self.fallback_name = config.LLM_FALLBACK_NAME
        self.fallback_url = config.LLM_FALLBACK_URL
        self.fallback_api_key = config.LLM_FALLBACK_API_KEY
        self.fallback_model = config.LLM_FALLBACK_MODEL
        self.fallback_timeout = config.LLM_FALLBACK_TIMEOUT

        self.ollama_url = ollama_url or config.OLLAMA_URL
        self.ollama_model = ollama_model or config.OLLAMA_MODEL
        self.ollama_enabled = (config.OLLAMA_ENABLED if ollama_enabled is None
                               else ollama_enabled)
        self.ollama_timeout = (config.OLLAMA_TIMEOUT if ollama_timeout is None
                               else ollama_timeout)

    @property
    def groq_available(self):
        return bool(self.groq_api_key)

    @property
    def available(self):
        return bool(self.providers())

    def openai_compatible_providers(self):
        """Configured /chat/completions providers, in the order they are tried.

        Built per call rather than cached, so that changing a key on an existing
        client takes effect.
        """
        providers = []
        if self.groq_api_key:
            providers.append({"name": "groq", "url": self.groq_url,
                              "key": self.groq_api_key, "model": self.groq_model,
                              "timeout": self.groq_timeout})
        if self.fallback_url and self.fallback_api_key:
            providers.append({"name": self.fallback_name, "url": self.fallback_url,
                              "key": self.fallback_api_key, "model": self.fallback_model,
                              "timeout": self.fallback_timeout})
        return providers

    def providers(self):
        """Names of the providers that would actually be attempted."""
        names = [p["name"] for p in self.openai_compatible_providers()]
        if self.ollama_enabled:
            names.append("ollama")
        return names

    def _call_openai_compatible(self, provider, prompt, system, max_tokens, temperature):
        response = requests.post(
            provider["url"],
            headers={"Authorization": f"Bearer {provider['key']}",
                     "Content-Type": "application/json"},
            json={
                "model": provider["model"],
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=provider["timeout"],
        )
        if response.status_code == 200:
            return _extract_json(response.json()["choices"][0]["message"]["content"])
        if response.status_code == 429:
            print(f"[LLM] {provider['name']} rate limit reached; trying the next provider")
        else:
            print(f"[LLM] {provider['name']} error {response.status_code}: "
                  f"{response.text[:200]}")
        return None

    def _call_ollama(self, prompt, max_tokens, temperature, timeout):
        response = requests.post(
            self.ollama_url,
            json={"model": self.ollama_model, "prompt": prompt, "stream": False,
                  "format": "json",
                  "options": {"num_predict": max_tokens, "temperature": temperature}},
            timeout=timeout,
        )
        if response.status_code == 200:
            return _extract_json(response.json().get("response", ""))
        return None

    def complete_json(self, prompt, system="Return valid JSON only, with no "
                      "markdown and no explanation.", max_tokens=2500,
                      temperature=0.7, ollama_timeout=None):
        """Return parsed JSON from the first provider that answers, else None.

        Never raises on provider failure: callers are expected to have a
        deterministic fallback, and a grading request must not fail a learner's
        submission because an optional model was unreachable.
        """
        for provider in self.openai_compatible_providers():
            try:
                result = self._call_openai_compatible(
                    provider, prompt, system, max_tokens, temperature)
                if result is not None:
                    return result
            except Exception as exc:
                print(f"[LLM] {provider['name']} request failed: {exc}")

        if self.ollama_enabled:
            try:
                result = self._call_ollama(
                    prompt, max_tokens, temperature,
                    self.ollama_timeout if ollama_timeout is None else ollama_timeout)
                if result is not None:
                    return result
            except Exception as exc:
                print(f"[LLM] Ollama request failed: {exc}")

        return None


llm_client = LLMClient()
