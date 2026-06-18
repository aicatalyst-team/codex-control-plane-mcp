from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout


def tracked_files() -> list[str]:
    output = run_git("ls-files")
    return [line for line in output.splitlines() if line]


def read_tracked_text(path: str) -> str | None:
    try:
        data = (ROOT / path).read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    return data.decode("utf-8", errors="ignore")


def private_content_patterns() -> list[tuple[str, re.Pattern[str]]]:
    private_windows_user = re.escape("\\".join(["C:", "Users", "shan"]))
    private_projects = re.escape("\\".join(["D:", "CodexProjects"]))
    private_bot = re.escape("\\".join(["D:", "Codex_TG_Bot"]))
    private_tracker = r"yt\." + re.escape("omega" + "future") + r"\.ru"
    project_profile_a = re.escape("Kadry" + "LO")
    project_profile_b = re.escape("Trico" + "lor")

    return [
        ("local Windows user path", re.compile(private_windows_user, re.IGNORECASE)),
        ("local Codex projects path", re.compile(private_projects, re.IGNORECASE)),
        ("local bot path", re.compile(private_bot, re.IGNORECASE)),
        ("private tracker host", re.compile(private_tracker, re.IGNORECASE)),
        ("private project profile A", re.compile(project_profile_a, re.IGNORECASE)),
        ("private project profile B", re.compile(project_profile_b, re.IGNORECASE)),
        ("OpenAI style API key", re.compile(r"sk-[A-Za-z0-9_-]{12,}")),
        ("Bearer token", re.compile(r"Bearer [A-Za-z0-9._~+/=-]{12,}")),
    ]


def dangerous_default_patterns() -> list[tuple[str, re.Pattern[str]]]:
    return [
        (
            "dangerous sandbox default",
            re.compile(r"CODEX_MCP_DEFAULT_SANDBOX\s*=.*danger", re.IGNORECASE),
        ),
        (
            "never approval default",
            re.compile(r"CODEX_MCP_DEFAULT_APPROVAL_POLICY\s*=.*never", re.IGNORECASE),
        ),
        (
            "danger-full-access described as default",
            re.compile(r"default.*danger-full-access", re.IGNORECASE),
        ),
        (
            "approval never described as default",
            re.compile(r"default.*approval.*never", re.IGNORECASE),
        ),
    ]


def check_forbidden_paths(paths: list[str]) -> list[str]:
    errors: list[str] = []
    forbidden_exact = {"AGENTS.MD", "PLAN.MD", ".env"}
    forbidden_prefixes = (".codex/", "state/", "logs/", "work/", "dist/")

    for path in paths:
        normalized = path.replace("\\", "/")
        name = Path(normalized).name
        if normalized in forbidden_exact:
            errors.append(f"forbidden tracked file: {path}")
        if name.startswith(".env.") and name != ".env.example":
            errors.append(f"private env file is tracked: {path}")
        if normalized.startswith(forbidden_prefixes):
            errors.append(f"private generated path is tracked: {path}")
        if normalized.endswith((".sqlite", ".sqlite3", ".sqlite-wal", ".sqlite-shm")):
            errors.append(f"SQLite state file is tracked: {path}")
    return errors


def check_private_content(paths: list[str]) -> list[str]:
    errors: list[str] = []
    patterns = private_content_patterns()
    for path in paths:
        text = read_tracked_text(path)
        if text is None:
            continue
        for label, pattern in patterns:
            if pattern.search(text):
                errors.append(f"{label} found in {path}")
    return errors


def check_public_defaults(paths: list[str]) -> list[str]:
    errors: list[str] = []
    allowed_roots = ("README.md", "README.ru.md", "docs/", ".env.example", "examples/")
    public_paths = [
        path
        for path in paths
        if path in allowed_roots or any(path.startswith(prefix) for prefix in allowed_roots)
    ]
    patterns = dangerous_default_patterns()
    for path in public_paths:
        text = read_tracked_text(path)
        if text is None:
            continue
        for label, pattern in patterns:
            if pattern.search(text):
                errors.append(f"{label} found in {path}")
    return errors


def main() -> int:
    try:
        paths = tracked_files()
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr)
        return 2

    errors: list[str] = []
    errors.extend(check_forbidden_paths(paths))
    errors.extend(check_private_content(paths))
    errors.extend(check_public_defaults(paths))

    if errors:
        print("Public hygiene check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Public hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
