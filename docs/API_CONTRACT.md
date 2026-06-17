# Codex Control Plane MCP API contract

Contract version: `1`.

MCP clients should call `codex_health_summary` on startup or reconnect and
verify:

- `version.serverName == "codex-control-plane-mcp"`
- `version.contractVersion == "1"`
- `version.toolSurfaceHash` is present and stable for the installed build
- required stable tools are present in `version.stableTools`

## MCP protocol

- Server entrypoint: `python -m codex_control_plane_mcp.server`
- Hook installer entrypoint: `codex-control-plane-mcp-hooks`
- Admin helper entrypoint: `codex-control-plane-mcp-admin`
- Legacy aliases: `openclaw-codex-mcp`, `openclaw-codex-mcp-hooks`
- Transport: MCP JSON-RPC over stdio
- `stdout`: JSON-RPC frames only
- Diagnostics/logs: file-only, default `logs/server.log`
- Domain/tool errors: returned from `tools/call` with `result.isError=true`
- JSON-RPC errors: reserved for protocol errors such as invalid methods or bad request params

Every tool declares `outputSchema`. Every tool result mirrors the same payload
in:

- `result.structuredContent`
- `result.content[0].text` as formatted JSON

Success:

```json
{"ok": true}
```

Domain/tool error:

```json
{
  "ok": false,
  "error": {
    "code": "CODEX_ERROR_CODE",
    "message": "Human readable message",
    "details": {},
    "retryable": false
  }
}
```

## Stable orchestration tools

These tools are the supported surface for long-running Codex orchestration:

- `codex_submit_task`
- `codex_get_operation_status`
- `codex_start_plan_workflow`
- `codex_get_workflow_status`
- `codex_approve_plan`
- `codex_list_pending_interactions`
- `codex_answer_pending_interaction`
- `codex_interrupt_turn`
- `codex_get_runtime_capabilities`
- `codex_health_summary`
- `codex_collect_diagnostics`
- `codex_repair_issue`

Stable tools are asynchronous or pollable when they can trigger long work. New
fields may be added, but existing input fields and machine-readable status/error
fields must not be removed without changing `contractVersion`.

## Write policy defaults

Server-level default write policy is configured by environment/config:

- `CODEX_MCP_DEFAULT_SANDBOX`, default `read-only`
- `CODEX_MCP_DEFAULT_APPROVAL_POLICY`, default `on-request`
- JSON config fields `default_sandbox_policy` and `default_approval_policy`

Explicit tool arguments always win over server defaults. A client may submit one
task with a stricter or more permissive policy without changing the server
configuration.

## Durable operation types

`codex_submit_task` supports these operation types:

- `start_chat`: create a Codex thread and start a turn.
- `send_message`: resume an existing thread and start a new turn.
- `execute_plan`: execute an approved Plan Mode workflow or existing chat plan.
- `steer_turn`: send extra text to an active turn through app-server `turn/steer`.

`steer_turn` requires `thread_id`, `expected_turn_id`, and `message`. It does
not create a new turn and does not participate in prompt duplicate detection.
After app-server accepts the steering input, the operation remains `running`
and follows the target turn until the turn reaches a terminal state.

For strict retry safety, pass `client_request_id`. Reusing the same
`client_request_id` returns the same steering operation and does not send a
second `turn/steer` request. Calls without `client_request_id` are treated as
new steering commands.

Status payloads for `steer_turn` include normal operation fields plus:

- `steerState.accepted`
- `steerState.targetThreadId`
- `steerState.targetTurnId`
- `steerState.clientUserMessageId`

If the target turn is missing, MCP returns `CODEX_TURN_NOT_FOUND`. If the target
turn is terminal or belongs to another thread, MCP returns `INVALID_ARGUMENT`.

## Turn progress journal

`codex_get_turn_status` and `codex_get_operation_status` return compact progress
data for tracked app-server turns by default.

Inputs:

- `progress_events`: number of recent progress events to return. Default `10`,
  max `100`. Use `0` to omit the progress block.
- `progress_max_chars`: max text returned for one progress event. Default
  `2000`.

Status payloads may include:

- `progressEvents`
- `progressEventCount`
- `latestProgressAt`
- `tokenUsage`
- `modelReroutes`
- `warnings`

Supported progress sources:

- `item/agentMessage/delta`
- `item/plan/delta`
- `item/reasoning/summaryPartAdded`
- `item/reasoning/summaryTextDelta`
- `thread/tokenUsage/updated`
- `model/rerouted`
- `warning`
- `configWarning`
- `guardianWarning`

`turn/diff/updated` is stored as safe metadata only. MCP keeps diff size and
line counts, but not the unified diff text. The progress journal also avoids raw
tool payloads and command output by default. It records only app-server-visible
progress summaries and does not expose hidden chain-of-thought.

`codex_collect_diagnostics` includes the same data in `progressJournal` and adds
progress entries to `timeline` with `source="turn_progress"`.

## Runtime capabilities

`codex_get_runtime_capabilities` is a read-only inventory endpoint for MCP
clients that need to understand the local Codex runtime before starting work.
It may start the MCP-owned app-server if it is not already running.

Input fields:

- `refresh`: default `false`. When `true`, bypasses the in-memory cache.
- `cwd`: optional working directory used for permission profile, hooks, and
  skills resolution. It must be inside `CODEX_ALLOWED_ROOTS`.
- `timeout_seconds`: per-method timeout. Default `2`, max `30`.
- `include_models`: default `true`.
- `include_hooks`: default `true`.
- `include_skills`: default `true`.

The tool caches one snapshot for five minutes per `cwd` and include-flag set.
Inventory calls are best effort. A timeout or error in one app-server method
does not fail the whole tool. The response stays `ok=true` and reports the
method state in `methodResults`.

Top-level result fields:

- `runtimeCapabilities`
- `cacheState`
- `methodResults`
- `warnings`
- `recommendedPollAfterSeconds=0`
- `pollRecommended=false`

`runtimeCapabilities` includes:

- `status`: `ok`, `partial`, or `unavailable`.
- `appServer`: process state plus redacted initialize metadata.
- `schemaMethods`: compact static method manifest with source, version, hash,
  method count, and method names.
- `models`: `id`, `model`, `displayName`, `isDefault`, `hidden`,
  `inputModalities`, reasoning effort fields, and service tier count.
- `permissionProfiles`: `id` and `description`.
- `sandboxReadiness`: Windows sandbox readiness status.
- `hooks`: counts grouped by cwd, event, source, trust, enabled state, and
  handler type. Raw hook commands and source paths are not returned.
- `skills`: counts grouped by cwd, scope, and enabled state. Skill names may be
  returned, but absolute paths are not returned.
- `modelProviderCapabilities`: `webSearch`, `imageGeneration`, and
  `namespaceTools`.

The endpoint intentionally excludes account email, account usage, and rate
limit data. Those fields need a separate privacy contract before they can be
exposed.

`codex_health_summary.runtimeCapabilities` contains only a compact subset from
the last collected runtime snapshot: status, cache age, model count, default
model, sandbox readiness, provider capabilities, and warning count. Health
summary does not collect inventory on its own.

## Compatibility tools

These tools remain available for UI support, direct reads, diagnostics, and old
clients, but new long-running write paths should use durable operations and
workflows:

- `codex_start_chat`
- `codex_send_message`
- `codex_execute_plan`
- `codex_list_projects`
- `codex_list_project_chats`
- `codex_list_active_chats`
- `codex_search_chats`
- `codex_get_chat_status`
- `codex_get_chat`
- `codex_get_turn_status`
- `codex_restart_app_server`
- `codex_get_app_server_status`
- `codex_get_diagnostic_logs`
- `codex_analyze_issue`

Low-level write compatibility tools return after `turn/start`. Prefer
`codex_submit_task` and polling for retry safety.

## Version block

`codex_health_summary.version` contains:

- `serverName`
- `serverVersion`
- `contractVersion`
- `toolSurfaceHash`
- `stableToolCount`
- `compatibilityToolCount`
- `stableTools`
- `compatibilityTools`
- `generatedAt`

`toolSurfaceHash` is a SHA-256 hash over tool names, descriptions, input/output
schemas, and contract groups. It is a fast compatibility probe, not a security
signature.

## Hook history block

`codex_health_summary` and `codex_collect_diagnostics` include a compact
`hookHistory` block:

- `enabled`
- `status`
- `installed`
- `events`
- `hooksJson`
- `configPath`
- `dbWritable`
- `threadCount`
- `turnCount`
- `messageCount`
- `lastHookEventAt`
- `warnings`

Top-level compatibility aliases are also returned: `hookHistoryStatus`,
`lastHookEventAt`, `hookInstalled`, and `hookDbWritable`.

Read/status tools may return these source values in addition to older values:

- `hook_history`
- `app_server+hook_history`
- `transcript+hook_history`
- `mixed`

Legacy `_kb_history` remains a fallback, but public installations should use:

```powershell
codex-control-plane-mcp-hooks install --state-db <PATH>
```

The hook installer stores `stateDb` as an absolute path even when `<PATH>` is
relative.

For write operations launched through `codex-app-server`, MCP mirrors the
accepted prompt, visible assistant messages, and turn status into the same hook
history tables. External Codex hooks remain the independent journal for normal
Codex user turns. The app-server mirror covers orchestrator-managed turns when
app-server does not run user hook commands.

## Stable error codes

Common stable error codes include:

- `INVALID_ARGUMENT`
- `CODEX_DUPLICATE_PROMPT_ACTIVE`
- `CODEX_BUSY`
- `CODEX_TIMEOUT`
- `CODEX_APP_SERVER_UNAVAILABLE`
- `CODEX_PENDING_INTERACTION_NOT_FOUND`
- `CODEX_PENDING_INTERACTION_UNAVAILABLE`
- `CODEX_THREAD_NOT_FOUND`
- `CODEX_TURN_NOT_FOUND`
- `CODEX_PROJECT_NOT_FOUND`
- `CODEX_TRANSCRIPT_NOT_FOUND`
- `CODEX_SEND_FAILED`
- `CODEX_SUMMARY_FAILED`

Clients should branch on `error.code` and treat `error.retryable` as the retry
hint. Human-readable `message` text is not a stable parsing target.

## Operational rules

- Do not mutate Codex internal SQLite or transcript files through MCP.
- Use app-server for write/control operations.
- For strict retry idempotency, pass `client_request_id`.
- Poll durable operations/workflows instead of holding long `tools/call` requests open.
- Do not run risky repairs without explicit `dry_run=false`; forced paths also require `force=true`.
- Prefer `refresh_catalog_and_history`; `refresh_catalog_and_kb` remains a compatibility alias.
