from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .diagnostics import redact_payload, redact_text


RUNTIME_CAPABILITIES_CACHE_TTL_SECONDS = 300
SCHEMA_METHODS_SOURCE = "codex-app-server-schema:ClientRequest.json:v2:compact"
SCHEMA_METHODS_VERSION = "2026-06-17"

SUPPORTED_APP_SERVER_METHODS = (
    "account/login/cancel",
    "account/login/start",
    "account/logout",
    "account/rateLimits/read",
    "account/read",
    "account/sendAddCreditsNudgeEmail",
    "account/usage/read",
    "app/list",
    "command/exec",
    "command/exec/resize",
    "command/exec/terminate",
    "command/exec/write",
    "config/batchWrite",
    "config/mcpServer/reload",
    "config/read",
    "config/value/write",
    "configRequirements/read",
    "experimentalFeature/enablement/set",
    "experimentalFeature/list",
    "externalAgentConfig/detect",
    "externalAgentConfig/import",
    "feedback/upload",
    "fs/copy",
    "fs/createDirectory",
    "fs/getMetadata",
    "fs/readDirectory",
    "fs/readFile",
    "fs/remove",
    "fs/unwatch",
    "fs/watch",
    "fs/writeFile",
    "hooks/list",
    "marketplace/add",
    "marketplace/remove",
    "marketplace/upgrade",
    "mcpServer/oauth/login",
    "mcpServer/resource/read",
    "mcpServer/tool/call",
    "mcpServerStatus/list",
    "model/list",
    "modelProvider/capabilities/read",
    "permissionProfile/list",
    "plugin/install",
    "plugin/installed",
    "plugin/list",
    "plugin/read",
    "plugin/share/checkout",
    "plugin/share/delete",
    "plugin/share/list",
    "plugin/share/save",
    "plugin/share/updateTargets",
    "plugin/skill/read",
    "plugin/uninstall",
    "review/start",
    "skills/config/write",
    "skills/extraRoots/set",
    "skills/list",
    "thread/approveGuardianDeniedAction",
    "thread/archive",
    "thread/compact/start",
    "thread/delete",
    "thread/fork",
    "thread/goal/clear",
    "thread/goal/get",
    "thread/goal/set",
    "thread/inject_items",
    "thread/list",
    "thread/loaded/list",
    "thread/metadata/update",
    "thread/name/set",
    "thread/read",
    "thread/resume",
    "thread/rollback",
    "thread/shellCommand",
    "thread/start",
    "thread/unarchive",
    "thread/unsubscribe",
    "turn/interrupt",
    "turn/start",
    "turn/steer",
    "windowsSandbox/readiness",
    "windowsSandbox/setupStart",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def schema_methods_block() -> dict[str, Any]:
    canonical = json.dumps(SUPPORTED_APP_SERVER_METHODS, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "source": SCHEMA_METHODS_SOURCE,
        "version": SCHEMA_METHODS_VERSION,
        "hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "methodCount": len(SUPPORTED_APP_SERVER_METHODS),
        "methods": list(SUPPORTED_APP_SERVER_METHODS),
    }


def compact_initialize_result(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    server_info = _dict(data.get("serverInfo") or data.get("server_info"))
    client = _dict(data.get("clientInfo") or data.get("client_info"))
    platform = data.get("platform") or _nested(data, "environment", "platform") or _nested(data, "metadata", "platform")
    user_agent = data.get("userAgent") or data.get("user_agent") or _nested(data, "metadata", "userAgent")
    return redact_payload(
        {
            "protocolVersion": data.get("protocolVersion") or data.get("protocol_version"),
            "serverInfo": {
                "name": server_info.get("name"),
                "version": server_info.get("version"),
            }
            if server_info
            else None,
            "clientInfo": {
                "name": client.get("name"),
                "version": client.get("version"),
            }
            if client
            else None,
            "platform": platform,
            "userAgent": user_agent,
        },
        max_string_chars=300,
    )


def compact_models(value: Any) -> dict[str, Any]:
    rows = _data_list(value, "models")
    items = []
    default_model = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        service_tiers = row.get("serviceTiers")
        if not isinstance(service_tiers, list):
            service_tiers = row.get("additionalSpeedTiers") if isinstance(row.get("additionalSpeedTiers"), list) else []
        supported_efforts = _reasoning_effort_ids(row.get("supportedReasoningEfforts"))
        item = {
            "id": _safe_text(row.get("id"), 160),
            "model": _safe_text(row.get("model"), 160),
            "displayName": _safe_text(row.get("displayName"), 160),
            "isDefault": bool(row.get("isDefault")),
            "hidden": bool(row.get("hidden")),
            "inputModalities": _safe_list(row.get("inputModalities"), max_items=10),
            "defaultReasoningEffort": _safe_text(row.get("defaultReasoningEffort"), 60),
            "supportedReasoningEfforts": supported_efforts,
            "serviceTierCount": len(service_tiers),
        }
        if item["isDefault"]:
            default_model = item["model"] or item["id"]
        items.append(item)
    return {
        "count": len(items),
        "defaultModel": default_model,
        "models": items,
        "nextCursorPresent": bool(_dict(value).get("nextCursor")),
    }


def compact_permission_profiles(value: Any) -> dict[str, Any]:
    rows = _data_list(value, "profiles")
    profiles = [
        {
            "id": _safe_text(row.get("id"), 160),
            "description": _safe_text(row.get("description"), 300),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    return {
        "count": len(profiles),
        "profiles": profiles,
        "nextCursorPresent": bool(_dict(value).get("nextCursor")),
    }


def compact_hooks(value: Any) -> dict[str, Any]:
    entries = _data_list(value, "entries")
    by_event: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_trust: dict[str, int] = {}
    by_enabled: dict[str, int] = {"enabled": 0, "disabled": 0}
    by_handler_type: dict[str, int] = {}
    warning_count = 0
    error_count = 0
    hook_count = 0
    managed_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        warning_count += len(entry.get("warnings") if isinstance(entry.get("warnings"), list) else [])
        error_count += len(entry.get("errors") if isinstance(entry.get("errors"), list) else [])
        hooks = entry.get("hooks") if isinstance(entry.get("hooks"), list) else []
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            hook_count += 1
            if hook.get("isManaged"):
                managed_count += 1
            _count(by_event, _safe_text(hook.get("eventName"), 80) or "unknown")
            _count(by_source, _safe_text(hook.get("source"), 80) or "unknown")
            _count(by_trust, _safe_text(hook.get("trustStatus"), 80) or "unknown")
            _count(by_handler_type, _safe_text(hook.get("handlerType"), 80) or "unknown")
            by_enabled["enabled" if hook.get("enabled") else "disabled"] += 1
    return {
        "cwdCount": len([entry for entry in entries if isinstance(entry, dict)]),
        "hookCount": hook_count,
        "managedCount": managed_count,
        "warningCount": warning_count,
        "errorCount": error_count,
        "byEvent": by_event,
        "bySource": by_source,
        "byTrust": by_trust,
        "byEnabled": by_enabled,
        "byHandlerType": by_handler_type,
    }


def compact_skills(value: Any, *, include_names: bool = True, max_names: int = 50) -> dict[str, Any]:
    entries = _data_list(value, "entries")
    by_scope: dict[str, int] = {}
    by_enabled: dict[str, int] = {"enabled": 0, "disabled": 0}
    names: list[str] = []
    error_count = 0
    skill_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        error_count += len(entry.get("errors") if isinstance(entry.get("errors"), list) else [])
        skills = entry.get("skills") if isinstance(entry.get("skills"), list) else []
        for skill in skills:
            if not isinstance(skill, dict):
                continue
            skill_count += 1
            _count(by_scope, _safe_text(skill.get("scope"), 80) or "unknown")
            by_enabled["enabled" if skill.get("enabled") else "disabled"] += 1
            name = _safe_text(skill.get("name"), 160)
            if include_names and name and len(names) < max_names:
                names.append(name)
    result: dict[str, Any] = {
        "cwdCount": len([entry for entry in entries if isinstance(entry, dict)]),
        "skillCount": skill_count,
        "errorCount": error_count,
        "byScope": by_scope,
        "byEnabled": by_enabled,
    }
    if include_names:
        result["names"] = sorted(set(names))
        result["namesTruncated"] = skill_count > len(result["names"])
    return result


def compact_provider_capabilities(value: Any) -> dict[str, Any]:
    data = _dict(value)
    return {
        "webSearch": _optional_bool(data.get("webSearch")),
        "imageGeneration": _optional_bool(data.get("imageGeneration")),
        "namespaceTools": _optional_bool(data.get("namespaceTools")),
    }


def compact_account_status(value: Any) -> dict[str, Any]:
    data = _dict(value)
    account = _dict(data.get("account"))
    requires_auth = bool(data.get("requiresOpenaiAuth"))
    account_type = _safe_text(account.get("type"), 80)
    plan_type = _safe_text(account.get("planType"), 80)
    email = account.get("email")
    return {
        "authenticated": bool(account) and not requires_auth,
        "requiresOpenaiAuth": requires_auth,
        "accountType": account_type,
        "planType": plan_type,
        "emailPresent": isinstance(email, str) and bool(email.strip()),
        "identityRedacted": True,
    }


def compact_account_usage(value: Any) -> dict[str, Any]:
    data = _dict(value)
    summary = _dict(data.get("summary"))
    daily_buckets = data.get("dailyUsageBuckets") if isinstance(data.get("dailyUsageBuckets"), list) else []
    return {
        "available": bool(summary or daily_buckets),
        "dailyBucketCount": len(daily_buckets),
        "hasDailyBuckets": bool(daily_buckets),
        "exactValuesRedacted": True,
        "summary": {
            "lifetimeUsageBand": _number_band(summary.get("lifetimeTokens"), [(0, "zero"), (1_000_000, "lt_1m"), (10_000_000, "1m_10m"), (100_000_000, "10m_100m")], "100m_plus"),
            "peakDailyUsageBand": _number_band(summary.get("peakDailyTokens"), [(0, "zero"), (100_000, "lt_100k"), (1_000_000, "100k_1m"), (10_000_000, "1m_10m")], "10m_plus"),
            "currentStreakDaysBand": _number_band(summary.get("currentStreakDays"), [(0, "zero"), (8, "1_7"), (31, "8_30"), (181, "31_180")], "181_plus"),
            "longestStreakDaysBand": _number_band(summary.get("longestStreakDays"), [(0, "zero"), (8, "1_7"), (31, "8_30"), (181, "31_180")], "181_plus"),
            "longestRunningTurnBand": _number_band(summary.get("longestRunningTurnSec"), [(60, "lt_1m"), (600, "1m_10m"), (3600, "10m_1h")], "1h_plus"),
        },
    }


def compact_rate_limits(value: Any) -> dict[str, Any]:
    data = _dict(value)
    primary = _compact_rate_limit_snapshot(data.get("rateLimits"))
    raw_buckets = data.get("rateLimitsByLimitId")
    buckets: list[dict[str, Any]] = []
    if isinstance(raw_buckets, dict):
        for key in sorted(raw_buckets):
            compact = _compact_rate_limit_snapshot(raw_buckets.get(key), bucket_key=str(key))
            if compact:
                buckets.append(compact)
    elif primary:
        buckets.append(primary)
    reached_type = primary.get("rateLimitReachedType") if primary else None
    return {
        "available": bool(primary or buckets),
        "bucketCount": len(buckets),
        "bucketsTruncated": len(buckets) > 10,
        "rateLimitReached": bool(reached_type and reached_type != "none")
        or any(bool(bucket.get("rateLimitReachedType") and bucket.get("rateLimitReachedType") != "none") for bucket in buckets),
        "rateLimitReachedType": reached_type,
        "planType": primary.get("planType") if primary else None,
        "credits": primary.get("credits") if primary else None,
        "primary": primary,
        "buckets": buckets[:10],
    }


def compact_sandbox_readiness(value: Any) -> dict[str, Any]:
    data = _dict(value)
    return {
        "status": _safe_text(data.get("status"), 80),
    }


def runtime_health_subset(snapshot: dict[str, Any] | None, *, cache_age_seconds: int | None) -> dict[str, Any]:
    if not snapshot:
        return {
            "status": "not_collected",
            "cacheAgeSeconds": None,
            "modelCount": None,
            "defaultModel": None,
            "sandboxReadiness": None,
            "providerCapabilities": None,
            "accountAuthenticated": None,
            "accountType": None,
            "planType": None,
            "rateLimitReached": None,
            "creditsAvailable": None,
            "usageAvailable": None,
            "warningsCount": 0,
        }
    capabilities = _dict(snapshot.get("runtimeCapabilities"))
    models = _dict(capabilities.get("models"))
    account_status = _dict(capabilities.get("accountStatus"))
    account_usage = _dict(capabilities.get("accountUsage"))
    rate_limits = _dict(capabilities.get("rateLimits"))
    credits = _dict(rate_limits.get("credits"))
    return {
        "status": capabilities.get("status") or "unknown",
        "cacheAgeSeconds": cache_age_seconds,
        "modelCount": models.get("count"),
        "defaultModel": models.get("defaultModel"),
        "sandboxReadiness": _dict(capabilities.get("sandboxReadiness")).get("status"),
        "providerCapabilities": capabilities.get("modelProviderCapabilities"),
        "accountAuthenticated": account_status.get("authenticated"),
        "accountType": account_status.get("accountType"),
        "planType": account_status.get("planType") or rate_limits.get("planType"),
        "rateLimitReached": rate_limits.get("rateLimitReached"),
        "creditsAvailable": credits.get("hasCredits"),
        "usageAvailable": account_usage.get("available"),
        "warningsCount": len(snapshot.get("warnings") if isinstance(snapshot.get("warnings"), list) else []),
    }


def _data_list(value: Any, fallback_key: str) -> list[Any]:
    data = _dict(value)
    if isinstance(data.get("data"), list):
        return list(data["data"])
    if isinstance(data.get(fallback_key), list):
        return list(data[fallback_key])
    if isinstance(value, list):
        return list(value)
    return []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _safe_text(value: Any, max_chars: int) -> str | None:
    if value in (None, ""):
        return None
    return redact_text(value, max_chars=max_chars)


def _safe_list(value: Any, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [redact_text(item, max_chars=80) for item in value[:max_items]]


def _reasoning_effort_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    efforts: list[str] = []
    for item in value:
        if isinstance(item, dict):
            effort = item.get("id") or item.get("value") or item.get("effort") or item.get("name")
        else:
            effort = item
        text = _safe_text(effort, 80)
        if text:
            efforts.append(text)
    return efforts


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _compact_rate_limit_snapshot(value: Any, *, bucket_key: str | None = None) -> dict[str, Any]:
    data = _dict(value)
    if not data:
        return {}
    limit_id = _safe_text(data.get("limitId") or bucket_key, 120)
    limit_name = _safe_text(data.get("limitName"), 120)
    public_key = limit_id if limit_id in {"codex"} else None
    identity = limit_id or limit_name or bucket_key or ""
    return {
        "knownBucket": public_key,
        "bucketHash": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16] if identity else None,
        "planType": _safe_text(data.get("planType"), 80),
        "rateLimitReachedType": _safe_text(data.get("rateLimitReachedType"), 80),
        "credits": _compact_credits(data.get("credits")),
        "primaryWindow": _compact_window(data.get("primary")),
        "secondaryWindow": _compact_window(data.get("secondary")),
        "individualLimit": _compact_individual_limit(data.get("individualLimit")),
        "identityRedacted": True,
    }


def _compact_credits(value: Any) -> dict[str, Any] | None:
    data = _dict(value)
    if not data:
        return None
    return {
        "hasCredits": _optional_bool(data.get("hasCredits")),
        "unlimited": _optional_bool(data.get("unlimited")),
        "balanceRedacted": "balance" in data,
    }


def _compact_window(value: Any) -> dict[str, Any] | None:
    data = _dict(value)
    if not data:
        return None
    used_percent = _safe_float(data.get("usedPercent"))
    return {
        "usedPercent": used_percent,
        "usedBand": _percent_band(used_percent),
        "resetInMinutes": _reset_in_minutes(data.get("resetsAt")),
        "windowDurationMins": _safe_int(data.get("windowDurationMins")),
    }


def _compact_individual_limit(value: Any) -> dict[str, Any] | None:
    data = _dict(value)
    if not data:
        return None
    return {
        "present": True,
        "remainingPercent": _safe_float(data.get("remainingPercent")),
        "resetInMinutes": _reset_in_minutes(data.get("resetsAt")),
        "valuesRedacted": bool({"limit", "used"} & set(data.keys())),
    }


def _number_band(value: Any, thresholds: list[tuple[int, str]], fallback: str) -> str | None:
    number = _safe_float(value)
    if number is None:
        return None
    if number < 0:
        return "unknown"
    for upper_bound, label in thresholds:
        if number < upper_bound or (upper_bound == 0 and number == 0):
            return label
    return fallback


def _percent_band(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 100:
        return "limit_reached"
    if value >= 90:
        return "near_limit"
    if value >= 70:
        return "high"
    if value >= 40:
        return "medium"
    return "low"


def _reset_in_minutes(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return 0
        timestamp_seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return max(0, int((datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc) - datetime.now(timezone.utc)).total_seconds() // 60))
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((parsed.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds() // 60))


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1
