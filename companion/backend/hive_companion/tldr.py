"""TLDR summarizer mode — Cachola et al., 2020 (arXiv:2004.15011).

"TLDR: Extreme summarization of scientific documents": a single controlled
sentence that captures the key contribution, written for a researcher
audience. Used across companion workflows: plan verdicts, timeline overlays,
KG node tooltips, and exposed as a read-only tool so any agentic workflow can
request one.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_TLDR_SYSTEM = (
    "You write TLDR-style extreme summaries of scientific content "
    "(Cachola et al., 2020): ONE sentence, at most 30 words, plain declarative, "
    "capturing the core contribution or finding — no filler like 'this paper "
    "discusses'. Write for a researcher audience."
)

_CACHE: dict[str, str] = {}
_CACHE_MAX = 512


def _cache_key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _fallback_tldr(text: str) -> str:
    """No-LLM fallback: first sentence, trimmed — better than nothing."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    m = re.search(r"^(.*?[.!?])", text)
    sentence = m.group(1) if m else text
    words = sentence.split()
    return " ".join(words[:28]) + ("…" if len(words) > 28 else "")


async def make_tldr(llm: Any, text: str, focus: str = "") -> str:
    """One-sentence TLDR of `text`; deterministic cache; graceful fallback."""
    body = (text or "").strip()
    if not body:
        return ""
    key = _cache_key(f"{focus}|{body[:2000]}")
    if key in _CACHE:
        return _CACHE[key]
    tldr = ""
    if llm is not None:
        try:
            user = f"Summarize for TLDR:{(' ' + focus) if focus else ''}\n\n{body[:4000]}"
            content = await llm.chat(system=_TLDR_SYSTEM, user=user, num_predict=70)
            # guard against rambling: hard-cut at the sentence boundary
            first = re.split(r"(?<=[.!?])\s", content.strip())[0]
            tldr = first[:240].strip()
        except Exception as exc:
            logger.debug("tldr generation failed: %s", exc)
    if not tldr:
        tldr = _fallback_tldr(body)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = tldr
    return tldr
