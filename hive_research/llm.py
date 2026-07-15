from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any

import requests

from .config import Config

logger = logging.getLogger(__name__)


class LLMInterface:
    def __init__(self, config: Config, gpu_mgr: Any = None) -> None:
        self.config = config
        self.gpu_mgr = gpu_mgr
        self.base_url = config.hive_base_url.rstrip("/")
        self.client_id = f"hive-research-gpu-{os.uname().nodename}" if hasattr(os, 'uname') else "hive-research-gpu"
        self._lock = threading.Lock()

    def _submit_job(self, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/api/jobs",
            json={"client_id": self.client_id, "job_type": job_type, "payload": payload},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def _poll_job(self, job_id: str, timeout: int = 300, interval: float = 0.3) -> dict[str, Any]:
        start = time.time()
        while time.time() - start < timeout:
            resp = requests.get(f"{self.base_url}/api/jobs/{job_id}", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") in ("completed", "failed"):
                if data["status"] == "failed":
                    raise RuntimeError(f"Hive job {job_id} failed: {data.get('error', 'unknown')}")
                result = data.get("result", {})
                if isinstance(result, dict):
                    return result
                return {"result": result}
            time.sleep(interval)
        raise TimeoutError(f"Hive job {job_id} timed out after {timeout}s")

    def _hive_request(
        self,
        job_type: str,
        payload: dict[str, Any],
        retries: int = 2,
        timeout: int = 300,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                job = self._submit_job(job_type, payload)
                return self._poll_job(job["job_id"], timeout=timeout)
            except Exception as e:
                last_error = e
                logger.warning(
                    "Hive request failed (attempt %d/%d): %s",
                    attempt + 1, retries, e,
                )
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        raise RuntimeError(
            f"Hive request ({job_type}) failed after {retries} retries"
        ) from last_error

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
        data = self._hive_request("chat", payload)
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
                results[idx] = self.generate(
                    prompt,
                    model=model,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                logger.error("Parallel generate task %d failed: %s", idx, e)
                results[idx] = ""

        threads = []
        for i, prompt in enumerate(prompts):
            t = threading.Thread(target=_run, args=(i, prompt), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=300)

        return results

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
            "prompt": text,
        }
        data = self._hive_request("embed", payload)
        return data.get("embedding", [])

    def embed_parallel(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        results: list[list[float]] = [[] for _ in texts]

        def _run(idx: int, text: str) -> None:
            try:
                results[idx] = self.embed(text, model=model)
            except Exception as e:
                logger.error("Parallel embed task %d failed: %s", idx, e)
                results[idx] = []

        threads = []
        for i, text in enumerate(texts):
            t = threading.Thread(target=_run, args=(i, text), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=120)

        return results

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        gpu_id: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.config.ollama_model,
            "messages": messages,
            "stream": False,
        }
        options: dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if options:
            payload["options"] = options
        try:
            data = self._hive_request("chat", payload, timeout=120)
            return data.get("message", {}).get("content", "")
        except Exception as e:
            logger.error("Chat request failed: %s", e)
            return ""

    def health_check(self, gpu_id: int | None = None) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/ollama/health", timeout=5)
            if r.status_code == 200:
                return r.json().get("status") == "healthy"
            return False
        except Exception:
            return False

    # ── Digest types ──

    DIGEST_TYPES = {
        "tldr": "One sentence capturing the absolute core finding.",
        "concept_digest": "Bulleted overview of the 5-8 most important concepts/terms with brief definitions.",
        "topic_digest": "Thematic breakdown of 3-5 topic areas. Explain how the paper engages with each.",
        "deep_digest": "Comprehensive 2-3 paragraph analysis covering: problem statement, methodology, key results, significance.",
        "methodology_digest": "Step-by-step breakdown of the methodology, proofs, or experimental setup. 2-3 paragraphs.",
        "findings_digest": "Bulleted list of key findings, results, and contributions.",
        "notation_digest": "List of important notation, symbols, and mathematical objects introduced.",
        "prerequisite_digest": "Background knowledge assumed by the paper. List 3-5 prerequisite topics.",
    }

    def generate_digests(
        self,
        text: str,
        digest_types: list[str] | None = None,
        model: str | None = None,
    ) -> dict[str, str]:
        types = digest_types or list(self.DIGEST_TYPES.keys())
        spec_lines = []
        for i, k in enumerate(types, 1):
            desc = self.DIGEST_TYPES.get(k, k)
            spec_lines.append(f"{i}. {k} (string): {desc}")
        system = (
            "You are a research paper analyst. Generate multiple digest views of the same paper. "
            "Respond ONLY with a valid JSON object. No markdown."
        )
        prompt = (
            "Analyze the following research paper and produce the following digest views as a JSON object:\n"
            f"{chr(10).join(spec_lines)}\n\n"
            f"Paper text:\n{self._compose_paper_text(text)}\n"
        )
        return self.extract_structured(prompt, system=system, temperature=0.2, model=model)

    # ── Help Noob: beginner-friendly explanations ──

    def generate_help_noob(
        self,
        text: str,
        analysis: dict | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        analysis_hint = ""
        if analysis:
            analysis_hint = (
                "\n\nThe structured analysis already extracted these. Make sure to explain ALL of them:\n"
                f"Title: {analysis.get('title', '')}\n"
                f"Topics: {json.dumps(analysis.get('topics', []))}\n"
                f"Concepts: {json.dumps([c.get('name', '') for c in analysis.get('concepts', [])])}\n"
                f"Theories: {json.dumps([t.get('name', '') for t in analysis.get('theories', [])])}\n"
            )
        system = (
            "You are a patient teacher who explains advanced research papers to a complete beginner. "
            "Use simple analogies, plain language, concrete examples. Avoid jargon — define it immediately. "
            "Respond ONLY with a valid JSON object. No markdown."
        )
        prompt = (
            "A beginner wants to understand this research paper. They have NO background in this field. "
            "Read the paper and produce a JSON object that teaches them everything they need to know:\n\n"
            "- title (string): the paper's title\n"
            "- eli5_summary (string): explain like they're 5 years old. 2-3 sentences. Use a simple analogy.\n"
            "- what_you_need_to_know_first (array of {topic, why}): 2-5 prerequisite topics to learn BEFORE reading this paper. For each, explain WHY it matters.\n"
            "- topics_explained (array of {name, simple_definition, analogy, why_it_matters}): for EACH broad topic area, give a plain-language definition, a real-world analogy, and why it matters.\n"
            "- concepts_explained (array of {name, simple_definition, analogy, why_it_matters}): for EACH key concept, explain it simply with an analogy and why it matters.\n"
            "- theories_explained (array of {name, eli5_explanation, example}): for each theory, give an ELI5 explanation and a concrete real-world example.\n"
            "- learning_path (array of strings): step-by-step ordered list of what to learn to fully understand this paper.\n"
            "- glossary (array of {term, definition}): every technical term, defined in one simple sentence.\n\n"
            f"{analysis_hint}"
            f"Paper text:\n{self._compose_paper_text(text)}\n"
        )
        return self.extract_structured(prompt, system=system, temperature=0.3, model=model)

    # ── Hive categorization ──

    def categorize_papers(
        self,
        paper_data: list[dict[str, Any]],
        model: str | None = None,
    ) -> list[dict[str, Any]]:
        system = (
            "You are a research librarian. Group papers into topic-based clusters (hives). "
            "Respond ONLY with a valid JSON array of objects. No markdown."
        )
        prompt = (
            "Group these research papers into 2-4 topic-based clusters (hives). "
            "Each hive should group papers that share a common topic area. "
            "EVERY paper MUST be assigned to exactly one hive. "
            "Return a JSON array of objects (MUST be an array), each with:\n"
            "  id: short unique id (e.g., 'complex-analysis')\n"
            "  label: human-readable label for the hive\n"
            "  paper_ids: array of paper IDs belonging to this hive\n\n"
            "IMPORTANT: Every paper_id from the input MUST appear in exactly one hive's paper_ids.\n"
            "Use the exact paper_id values provided, not titles.\n\n"
            f"Papers:\n{json.dumps(paper_data, indent=2)[:24000]}\n"
        )
        result = self.extract_structured(prompt, system=system, temperature=0.1, model=model)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
        return []

    @staticmethod
    def _compose_paper_text(text: str, head: int = 12000, tail: int = 6000) -> str:
        if len(text) <= head + tail:
            return text
        return (
            text[:head]
            + "\n\n[... middle of paper truncated for length ...]\n\n"
            + text[-tail:]
        )

    def extract_structured(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        gpu_id: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        system_msg = system or (
            "You are a precise information extraction system. "
            "Respond ONLY with valid JSON. No markdown, no explanation."
        )
        text = self.generate(prompt, model=model, system=system_msg, temperature=temperature, gpu_id=gpu_id)
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
