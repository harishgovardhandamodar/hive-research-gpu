from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

import requests

from .config import Config
from .gpu import GPUManager

logger = logging.getLogger(__name__)


class GatewayBusy(RuntimeError):
    """The gateway had no free concurrency slot within its own 600s wait.

    Distinct from a transport failure: retrying immediately re-enters the same
    queue, so the honest answer is to give up and let the caller degrade (the
    pipeline already treats a failed analysis as a partial result) rather than
    burn minutes re-asking.
    """


def canonical_model_name(name: str) -> tuple[str, str]:
    """Split a model reference into comparable ``(base, tag)``.

    A missing tag means ``latest`` -- that is Ollama's own rule, so
    ``nomic-embed-text`` and ``nomic-embed-text:latest`` are one model and
    comparing the raw strings would report a substitution on every embed.

    Two *named* tags are left distinct: ``qwen3.8:27b`` and
    ``qwen3.8:latest`` happen to share a digest on these hosts, but that is a
    property of what is installed, not of the names, and a quantisation switch
    (:large) really is a different model.
    """
    base, _, tag = name.partition(":")
    return base.strip().lower(), (tag.strip().lower() or "latest")


def _is_different_model(served: str, requested: str) -> bool:
    """True only when the two names denote genuinely different models."""
    if not served or not requested:
        return False
    return canonical_model_name(served) != canonical_model_name(requested)


class LLMInterface:
    def __init__(self, config: Config, gpu_mgr: GPUManager | None = None) -> None:
        self.config = config
        self.gpu_mgr = gpu_mgr
        self.base_url = config.ollama_base_url.rstrip("/")
        self.embed_base_url = config.ollama_embed_base_url.rstrip("/")
        self._lock = threading.Lock()
        # What the gateway actually served, as opposed to what was asked for.
        # Per-thread: parallel paper workers share one LLMInterface, and the
        # swarm issues several calls per paper, so a plain attribute would let
        # paper B's response overwrite paper A's provenance between A's set and
        # read. One paper per thread is the existing concurrency model, so
        # thread-local is exactly the right scope.
        self._local = threading.local()
        # Whether this endpoint tells us what it served. A gateway build
        # without the routing-header contract substitutes models silently, so
        # "asked for X" is not evidence that X answered. Observed on an older
        # axiom-1 fox-services: asked for qwen3.8:27b, served llama3.2:3b,
        # no header. Tracked so the operator is told once, loudly, instead of
        # discovering later that every note's analyzed_by field is a guess.
        self.served_model_verifiable = True
        self._warned_unverifiable = False

    @property
    def last_served_model(self) -> str:
        return getattr(self._local, "served_model", "")

    @last_served_model.setter
    def last_served_model(self, value: str) -> None:
        self._local.served_model = value

    @property
    def last_served_node(self) -> str:
        return getattr(self._local, "served_node", "")

    @last_served_node.setter
    def last_served_node(self, value: str) -> None:
        self._local.served_node = value

    def _get_base_url(self, gpu_id: int | None = None) -> str:
        # A gpu_id is a scheduling hint, not a routing instruction. Honouring it
        # as one sends the call to a bare per-GPU Ollama and out of the gateway:
        # unattributed in telemetry, no X-Served-Model to record provenance
        # from, managed pool skipped. Only do that when it is asked for.
        if (gpu_id is not None and self.gpu_mgr
                and self.gpu_mgr.device_count() > 0
                and self.config.ollama_direct_gpu_routing):
            return self.gpu_mgr.get_ollama_url(gpu_id).rstrip("/")
        return self.base_url

    def _headers(self) -> dict[str, str]:
        """Headers every gateway request carries.

        ``X-Service-Name`` is not decoration: the gateway attributes every
        inference row to it, and without it this whole app's usage lands in
        the telemetry table as ``gateway-unknown``, indistinguishable from
        curl. ``X-Requestor`` separates a person's query (user) from a
        pipeline step nobody asked for (subagent), so a bulk re-ingest does
        not read as a burst of human questions.
        """
        return {
            "X-Service-Name": self.config.ollama_service_name,
            "X-Requestor": self.config.ollama_requestor,
        }

    def _note_served_model(self, requested: str, resp: requests.Response, endpoint: str) -> str:
        """Record which model actually answered, and complain if it is not the one asked for.

        The gateway is allowed to substitute (it prefers an already-loaded
        model to pay a cold load). That is the right behaviour for latency and
        the wrong behaviour for provenance: a paper note written by a 3B model
        must not say a 27B model wrote it. The gateway reports the substitution
        in X-Served-Model, so read it here and keep the truth for the notes.

        Tag-insensitive on purpose. "nomic-embed-text" and
        "nomic-embed-text:latest" are one model under two names, and an embed
        runs on every chunk of every ingest -- a warning there would fire
        constantly for a substitution that did not happen, and an operator who
        sees constant warnings stops reading them.
        """
        served = resp.headers.get("X-Served-Model") or ""
        if not served:
            # No header means the endpoint does not report what it served. Do
            # not fill in `requested`: that is a claim, and this is not
            # evidence. Flag it instead, once.
            self.served_model_verifiable = False
            if not self._warned_unverifiable:
                self._warned_unverifiable = True
                logger.warning(
                    "%s returned no X-Served-Model, so the served model cannot "
                    "be verified. If this endpoint substitutes models, note "
                    "provenance (analyzed_by) records the model we asked for, "
                    "not the one that wrote the note. Update the gateway; a "
                    "fox-services with the routing-header contract emits it "
                    "on every inference response.",
                    self.base_url or "the configured Ollama endpoint",
                )
            return requested
        # Remembered even when it matches the request: the notes need a model
        # name, and "we asked for X and got X" is only knowable by asking.
        self.last_served_model = served
        node = resp.headers.get("X-Served-Node") or ""
        self.last_served_node = node
        if _is_different_model(served, requested):
            logger.warning(
                "Gateway served %s for a %s request that asked for %s (node=%s): %s",
                served, endpoint, requested, node or "local",
                resp.headers.get("X-Routing-Reason") or "no reason given",
            )
        return served

    def _request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        retries: int = 3,
        gpu_id: int | None = None,
        base_url_override: str = "",
    ) -> dict[str, Any]:
        base_url = base_url_override or self._get_base_url(gpu_id)
        url = f"{base_url}/api/{endpoint}"
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                resp = requests.post(url, json=payload, headers=self._headers(),
                                     timeout=self.config.ollama_timeout)
                if resp.status_code == 429:
                    # The gateway held the request until its 600s slot timeout
                    # ran out. Retrying immediately just queues behind the
                    # same contention, so back off hard and let the caller see
                    # a real error rather than an empty string.
                    raise GatewayBusy(resp.text[:300])
                resp.raise_for_status()
                requested = str(payload.get("model") or "")
                self._note_served_model(requested, resp, endpoint)
                return resp.json()
            except requests.RequestException as e:
                last_error = e
                logger.warning(
                    "Ollama request failed to %s (attempt %d/%d, GPU %s): %s",
                    url, attempt + 1, retries,
                    str(gpu_id) if gpu_id is not None else "default",
                    e,
                )
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        raise RuntimeError(
            f"Ollama request to {endpoint} on GPU {gpu_id} failed after {retries} retries: {last_error}"
        )

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        gpu_id: int | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": model or self.config.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None
                else self.config.ollama_temperature,
                "num_predict": max_tokens if max_tokens is not None
                else self.config.ollama_max_tokens,
            },
        }
        if gpu_id is None and self.gpu_mgr:
            gpu_id = self.gpu_mgr.get_next_llm_gpu()
        data = self._request("chat", payload, gpu_id=gpu_id)
        return data.get("message", {}).get("content", "")

    def generate_parallel(
        self,
        prompts: list[str],
        model: str | None = None,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> list[str]:
        results: list[str] = [""] * len(prompts)

        def _run(idx: int, prompt: str) -> None:
            try:
                gpu_id = idx if self.gpu_mgr and self.gpu_mgr.device_count() > 0 else None
                results[idx] = self.generate(
                    prompt,
                    model=model,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    gpu_id=gpu_id,
                )
            except Exception as e:
                logger.error("Parallel generate task %d failed: %s", idx, e)
                results[idx] = ""

        threads = []
        for i, prompt in enumerate(prompts):
            t = threading.Thread(target=_run, args=(i, prompt), daemon=True)
            t.start()
            threads.append(t)

        # One deadline for the whole fan-out, not a per-thread budget: the
        # threads run concurrently, so the slowest one bounds the batch. It
        # must exceed the per-request timeout -- a 300s join against a 660s
        # request walks away from a thread whose gateway slot is still held and
        # reports every prompt as empty, which reads as "the model said nothing".
        deadline = time.monotonic() + self.config.ollama_timeout + 30
        for t in threads:
            t.join(timeout=max(0.0, deadline - time.monotonic()))

        stuck = sum(1 for i, t in enumerate(threads)
                    if t.is_alive() and not results[i])
        if stuck:
            logger.warning(
                "%d/%d parallel generate tasks did not finish within %ds "
                "(gateway still holding their slots?); their prompts returned empty",
                stuck, len(threads), int(self.config.ollama_timeout))
        return results

    def extract_structured(
        self,
        prompt: str,
        model: str | None = None,
        gpu_id: int | None = None,
    ) -> dict[str, Any]:
        system = (
            "You are a precise information extraction system. "
            "Respond ONLY with valid JSON. No markdown, no explanation."
        )
        text = self.generate(prompt, model=model, system=system, temperature=0.0, gpu_id=gpu_id)
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        repaired = self._repair_json(text)
        if repaired is not None:
            logger.warning("Repaired truncated JSON from LLM (%d chars) keys=%s",
                           len(text), list(repaired.keys()))
            return repaired
        logger.error("Failed to parse JSON from LLM response (len=%d): %s",
                     len(text), text[:500])
        return {}

    @staticmethod
    def _repair_json(text: str) -> dict[str, Any] | None:
        if not text or text[0] != '{':
            return None
        text = text.strip()
        # Trim trailing non-JSON content after the last balanced '}'
        depth = 0
        last_balanced = -1
        in_str = False
        escaped = False
        for i, ch in enumerate(text):
            if escaped:
                escaped = False
                continue
            if ch == '\\':
                escaped = True
                continue
            if ch == '"' and not escaped:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    last_balanced = i
        if last_balanced >= 0:
            text = text[:last_balanced + 1]
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        text = re.sub(
            r':\s*(\d[\w.\-+]*[a-zA-Z][\w.\-+]*)\s*([,}\]])',
            r': "\1"\2',
            text,
        )
        text = re.sub(
            r'"(\w+)":\s*\{\s*("[^"]*"\s*(?:,\s*"[^"]*"\s*)*)\s*\}',
            r'"\1": [\2]',
            text,
        )
        # Remove stray quotes between closing brackets/braces (e.g. ]"}) → ]})
        text = re.sub(r'\]"\s*([\]}])', r']\1', text)
        text = re.sub(r'\}"\s*([\]}])', r'}\1', text)
        # Fix spurious "[" as first array element (missing comma before next string)
        text = re.sub(r'(?<=[\[,])\s*"\s*\[\s*"(?=[^,\]"\s])', '"', text)
        stack: list[str] = []
        in_str = False
        escaped = False
        for ch in text:
            if escaped:
                escaped = False
                continue
            if ch == '\\':
                escaped = True
                continue
            if ch == '"' and not escaped:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in '([{':
                stack.append(ch)
            elif ch == ')':
                if stack and stack[-1] == '(':
                    stack.pop()
            elif ch == ']':
                if stack and stack[-1] == '[':
                    stack.pop()
            elif ch == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
        if in_str:
            text += '"'
        close_map = {'{': '}', '[': ']', '(': ')'}
        for ch in reversed(stack):
            text += close_map.get(ch, '}')
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        fields = {}
        for key in ('summary', 'notes', 'lineage_notes'):
            key_pattern = f'"{key}"'
            start = text.find(key_pattern)
            if start < 0:
                continue
            pos = start + len(key_pattern)
            while pos < len(text) and text[pos] in ' \t\n\r:':
                pos += 1
            if pos >= len(text) or text[pos] != '"':
                continue
            pos += 1
            value_chars: list[str] = []
            while pos < len(text):
                ch = text[pos]
                if ch == '\\':
                    pos += 1
                    if pos < len(text):
                        value_chars.append(text[pos])
                    pos += 1
                    continue
                if ch == '"':
                    break
                value_chars.append(ch)
                pos += 1
            if value_chars:
                fields[key] = ''.join(value_chars)
        if fields:
            return fields
        return None

    def embed(self, text: str, model: str | None = None, gpu_id: int | None = None) -> list[float]:
        payload = {
            "model": model or self.config.ollama_embed_model,
            "input": text,
        }
        embed_url = self.embed_base_url
        if gpu_id is None and self.gpu_mgr and not embed_url:
            gpu_id = self.gpu_mgr.get_next_embed_gpu()
        try:
            data = self._request("embed", payload, gpu_id=gpu_id, retries=1, base_url_override=embed_url)
        except RuntimeError as e:
            # Older Ollama builds / proxies only implement the legacy
            # /api/embeddings endpoint — fall back transparently.
            if "501" in str(e) or "404" in str(e):
                legacy = dict(payload)
                legacy["prompt"] = legacy.pop("input")
                data = self._request("embeddings", legacy, gpu_id=gpu_id, base_url_override=embed_url)
            else:
                raise
        if isinstance(data.get("embeddings"), list) and data["embeddings"]:
            return data["embeddings"][0]
        return data.get("embedding", [])

    def embed_parallel(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        results: list[list[float]] = [[] for _ in texts]

        def _run(idx: int, text: str) -> None:
            try:
                gpu_id = idx % max(self.gpu_mgr.device_count(), 1) if self.gpu_mgr else None
                results[idx] = self.embed(text, model=model, gpu_id=gpu_id)
            except Exception as e:
                logger.error("Parallel embed task %d failed: %s", idx, e)
                results[idx] = []

        threads = []
        for i, text in enumerate(texts):
            t = threading.Thread(target=_run, args=(i, text), daemon=True)
            t.start()
            threads.append(t)

        # Same single-deadline reasoning as generate_parallel: these run
        # concurrently, and abandoning one at 120s while its gateway slot is
        # still held just guarantees a duplicate embed later.
        deadline = time.monotonic() + self.config.ollama_timeout + 30
        for t in threads:
            t.join(timeout=max(0.0, deadline - time.monotonic()))

        stuck = sum(1 for i, t in enumerate(threads)
                    if t.is_alive() and not results[i])
        if stuck:
            logger.warning(
                "%d/%d parallel embed tasks did not finish within %ds; "
                "those chunks were stored with no vector",
                stuck, len(threads), int(self.config.ollama_timeout))
        return results

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        gpu_id: int | None = None,
    ) -> str:
        base_url = self._get_base_url(gpu_id)
        url = f"{base_url}/api/chat"
        payload: dict[str, Any] = {
            "model": model or self.config.ollama_model,
            "messages": messages,
            "stream": False,
        }
        try:
            # The configured timeout, not the historical hardcoded 120s. The
            # gateway can hold a request for its own 600s slot wait before it
            # even forwards; a 120s client read gave up while the slot was
            # still held, so a busy gateway looked like a dead one.
            resp = requests.post(url, json=payload, headers=self._headers(),
                                 timeout=self.config.ollama_timeout)
            if resp.status_code == 429:
                raise GatewayBusy(resp.text[:300])
            resp.raise_for_status()
            data = resp.json()
            requested = str(payload.get("model") or "")
            self._note_served_model(requested, resp, "chat")
            return data.get("message", {}).get("content", "")
        except GatewayBusy as e:
            logger.error("Gateway busy for chat on GPU %s (slot wait timed out): %s",
                         str(gpu_id), e)
            return ""
        except requests.RequestException as e:
            logger.error("Chat request failed on GPU %s: %s", str(gpu_id), e)
            return ""

    def gateway_status(self) -> dict[str, Any]:
        """What the gateway is doing right now: slots, queue depth, policy.

        Best effort by design -- this is a diagnostic panel, and an
        unreachable gateway must not turn into an error on a route that is
        otherwise serving.
        """
        out: dict[str, Any] = {
            "base_url": self.base_url,
            "embed_base_url": self.embed_base_url or None,
            "service_name": self.config.ollama_service_name,
            "reachable": False,
            # False once a response arrived without X-Served-Model. The panel
            # shows this so a reader knows analyzed_by is the requested model
            # rather than the one that answered.
            "served_model_verifiable": self.served_model_verifiable,
        }
        base = self.base_url.rstrip("/")
        try:
            r = requests.get(f"{base}/api/router/status", timeout=5)
            if r.status_code == 200:
                st = r.json()
                slots = st.get("slots") or {}
                out.update(
                    reachable=True,
                    gateway_enabled=st.get("gateway_enabled"),
                    loaded_models=slots.get("loaded_models") or [],
                    active_requests=st.get("active_requests") or [],
                    pending=st.get("queues", {}).get("pending"),
                    active=st.get("queues", {}).get("active"),
                    policy=(st.get("policy") or {}).get("preferred") or [],
                )
                return out
        except Exception as e:
            out["error"] = str(e)[:200]
        # Not a gateway, or not reachable: fall back to plain model discovery
        # so the panel can still say what is installed.
        try:
            r = requests.get(f"{base}/api/tags", timeout=5)
            if r.status_code == 200:
                out["models"] = [m.get("name") or m.get("model")
                                 for m in (r.json().get("models") or [])]
                out["reachable"] = True
        except Exception as e:
            out.setdefault("error", str(e)[:200])
        return out

    def health_check(self, gpu_id: int | None = None) -> bool:
        try:
            base_url = self._get_base_url(gpu_id)
            r = requests.get(f"{base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False
