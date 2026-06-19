from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import TranscriptMessage, TranscriptSummary
from .plan_quality import extract_proposed_plan, plan_hash_for_text
from .transcripts import parse_transcript


def import_transcript_to_tracking(storage: Any, path: Path, *, archived: bool = False) -> dict[str, Any]:
    summary = parse_transcript(
        path,
        archived=archived,
        include_tool_calls=False,
        include_tool_outputs=False,
        include_command_outputs=False,
        include_reasoning=False,
    )
    return import_transcript_summary_to_tracking(storage, summary)


def import_transcript_summary_to_tracking(storage: Any, summary: TranscriptSummary) -> dict[str, Any]:
    thread_id = summary.thread_id or ""
    if not thread_id:
        return {
            "imported": False,
            "reason": "missing_thread_id",
            "turnsImported": 0,
            "messagesImported": 0,
            "plansImported": 0,
        }

    messages_by_turn: dict[str, list[TranscriptMessage]] = {}
    messages_imported = 0
    plans_imported = 0
    for message in summary.messages:
        turn_id = message.turn_id or ""
        if not turn_id or message.role not in {"user", "assistant", "system"}:
            continue
        messages_by_turn.setdefault(turn_id, []).append(message)

    for turn_id, turn in summary.turns.items():
        turn_messages = messages_by_turn.get(turn_id, [])
        assistant_messages = [message for message in turn_messages if message.role == "assistant" and (message.text or "").strip()]
        final_message = assistant_messages[-1].text if turn.status == "completed" and assistant_messages else None
        last_assistant = assistant_messages[-1].text if assistant_messages else None
        storage.upsert_tracked_turn(
            {
                "turn_id": turn_id,
                "thread_id": thread_id,
                "chat_id": thread_id,
                "project_id": None,
                "project_path": summary.project_path,
                "status": turn.status or "unknown",
                "started_at": turn.started_at,
                "updated_at": turn.completed_at or summary.updated_at or turn.started_at,
                "completed_at": turn.completed_at,
                "first_message_at": turn_messages[0].created_at if turn_messages else turn.started_at,
                "final_message": final_message,
                "last_assistant_message": last_assistant,
                "last_error": None,
                "source": "transcript",
                "last_event_seq": turn.source_line_end or turn.source_line_start or 0,
                "clear_last_error": True,
            }
        )

        for sequence, message in enumerate(turn_messages, 1):
            event_hash = _message_event_hash(summary.transcript_path, message, sequence)
            if storage.record_tracked_turn_message(
                {
                    "event_hash": event_hash,
                    "turn_id": turn_id,
                    "thread_id": thread_id,
                    "role": message.role,
                    "text": message.text or "",
                    "created_at": message.created_at,
                    "sequence": sequence,
                    "event_type": f"transcript/{message.metadata.get('payload_type') or message.role}",
                    "payload_json": json.dumps(
                        {
                            "source": "transcript_import",
                            "messageId": message.message_id,
                            "sourceLineStart": message.source_line_start,
                            "sourceLineEnd": message.source_line_end,
                        },
                        ensure_ascii=False,
                    ),
                }
            ):
                messages_imported += 1

        for message in assistant_messages:
            extracted_plan = extract_proposed_plan(message.text)
            if not extracted_plan:
                continue
            plan_text = (message.text or "").strip()
            item_id = f"{turn_id}:transcript-proposed-plan:{plan_hash_for_text(plan_text) or 'unknown'}"
            storage.upsert_tracked_plan_item(
                {
                    "item_id": item_id,
                    "turn_id": turn_id,
                    "thread_id": thread_id,
                    "status": "completed",
                    "text": plan_text,
                    "created_at": message.created_at or turn.completed_at or summary.updated_at,
                    "updated_at": message.created_at or turn.completed_at or summary.updated_at,
                    "completed_at": turn.completed_at or message.created_at or summary.updated_at,
                    "sequence": message.source_line_start or 0,
                    "payload_json": json.dumps(
                        {
                            "source": "transcript_import",
                            "transcriptPath": summary.transcript_path,
                            "messageId": message.message_id,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            plans_imported += 1

    return {
        "imported": True,
        "threadId": thread_id,
        "turnsImported": len(summary.turns),
        "messagesImported": messages_imported,
        "plansImported": plans_imported,
        "parseErrors": summary.parse_errors,
        "source": "transcript",
    }


def _message_event_hash(transcript_path: str, message: TranscriptMessage, sequence: int) -> str:
    raw = "|".join(
        [
            transcript_path,
            str(message.message_id or ""),
            str(message.turn_id or ""),
            str(message.role or ""),
            str(message.created_at or ""),
            str(sequence),
            str(message.text or "")[:200],
        ]
    )
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
