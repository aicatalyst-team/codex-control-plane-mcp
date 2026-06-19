from __future__ import annotations

import re
import json
from typing import Any

from .prompt_dedup import normalize_prompt, prompt_hash


PROPOSED_PLAN_RE = re.compile(r"<proposed_plan>\s*(.*?)\s*</proposed_plan>", re.IGNORECASE | re.DOTALL)

BLOCKER_MARKERS = (
    "createprocessasuserw failed",
    "не могу",
    "не удалось",
    "нужен доступ",
    "без доступа",
    "нет доступа",
    "не буду реконструировать",
    "cannot access",
    "can't access",
    "permission denied",
    "access is denied",
    "blocked",
)

QUESTION_MARKERS = (
    "нужно уточнить",
    "уточните",
    "пришлите",
    "which option",
    "please provide",
)


def extract_proposed_plan(text: str | None) -> str | None:
    if not text:
        return None
    match = PROPOSED_PLAN_RE.search(text)
    if not match:
        return None
    inner = match.group(1).strip()
    return inner or text.strip()


def classify_plan_text(text: str | None) -> str:
    raw = (text or "").strip()
    if not raw:
        return "unknown"
    lowered = raw.lower()
    if extract_proposed_plan(raw):
        return "valid_plan"
    if any(marker in lowered for marker in BLOCKER_MARKERS):
        return "blocker"
    if any(marker in lowered for marker in QUESTION_MARKERS) and "?" in raw:
        return "question"
    if len(raw) < 300:
        return "partial"
    return "needs_review"


def classify_plan_artifact(text: str | None, payload_json: str | None = None) -> str:
    text_quality = classify_plan_text(text)
    if text_quality in {"valid_plan", "blocker", "question"}:
        return text_quality
    payload = _payload_from_json(payload_json)
    if _is_structured_plan_payload(payload) and (text or "").strip():
        return "valid_plan"
    if payload_json is not None and not _is_untrusted_fallback_payload(payload) and (text or "").strip():
        return "valid_plan"
    return text_quality


def plan_quality_payload(text: str | None, payload_json: str | None = None) -> dict[str, Any]:
    quality = classify_plan_artifact(text, payload_json)
    return {
        "quality": quality,
        "valid": quality == "valid_plan",
        "requiresReview": quality in {"needs_review", "partial", "unknown"},
        "isBlocker": quality in {"blocker", "refusal"},
    }


def _payload_from_json(payload_json: str | None) -> dict[str, Any]:
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_structured_plan_payload(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    if _is_untrusted_fallback_payload(payload):
        return False
    method = str(payload.get("method") or "")
    if method in {"item/plan/delta", "turn/plan/updated"}:
        return True
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    item = params.get("item") if isinstance(params.get("item"), dict) else {}
    return method == "item/completed" and item.get("type") == "plan"


def _is_untrusted_fallback_payload(payload: dict[str, Any]) -> bool:
    return payload.get("source") in {"assistant_final_message_fallback", "transcript_import"}


def plan_hash_for_text(text: str | None) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    return prompt_hash(normalize_prompt(raw))


def _truncate_for_status(text: str, *, max_chars: int) -> tuple[str, dict[str, Any]]:
    if len(text) <= max_chars:
        return text, {}
    return text[:max_chars] + "\n[truncated]", {"truncated": True, "original_chars": len(text)}


def plan_candidate_payload(
    *,
    turn_id: str,
    thread_id: str,
    text: str,
    source: str,
    item_id: str | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
    completed_at: str | None = None,
    max_chars: int = 8000,
) -> dict[str, Any]:
    quality = plan_quality_payload(text)
    truncated, meta = _truncate_for_status(text, max_chars=max_chars)
    return {
        "turnId": turn_id,
        "threadId": thread_id,
        "itemId": item_id,
        "planHash": plan_hash_for_text(text),
        "source": source,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "completedAt": completed_at,
        "markdown": truncated,
        "text": truncated,
        "truncated": bool(meta.get("truncated")),
        "originalChars": meta.get("original_chars"),
        "planQuality": quality.get("quality"),
        **quality,
    }
