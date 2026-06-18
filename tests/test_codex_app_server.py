from __future__ import annotations

from unittest.mock import patch

from tests.helpers import *

from openclaw_codex_mcp.codex_app_server import CodexAppServerClient


class _FakeProcess:
    pid = 4242
    returncode = None
    stdin = object()
    stdout = object()
    stderr = object()

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode


class CodexAppServerClientTests(unittest.TestCase):
    def test_start_passes_configured_codex_home_to_app_server_env(self) -> None:
        async def scenario() -> tuple[dict, dict]:
            with TemporaryDirectory() as tmp:
                root = Path(tmp)
                config = _search_service_config(root, root / ".codex" / "state_5.sqlite")
                config.codex_binary_path.write_text("", encoding="utf-8")
                storage = McpStorage(root / "mcp.sqlite")
                storage.connect()
                client = CodexAppServerClient(config, storage)
                captured: dict[str, object] = {}

                async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
                    captured["args"] = args
                    captured["kwargs"] = kwargs
                    return _FakeProcess()

                async def fake_request(method: str, params: dict | None, timeout_seconds: float | None = None) -> dict:
                    return {"method": method, "params": params, "timeoutSeconds": timeout_seconds}

                async def fake_notify(method: str, params: dict) -> None:
                    captured["notify"] = {"method": method, "params": params}

                async def noop() -> None:
                    return None

                client.request = fake_request  # type: ignore[method-assign]
                client.notify = fake_notify  # type: ignore[method-assign]
                client._read_stdout_loop = noop  # type: ignore[method-assign]
                client._read_stderr_loop = noop  # type: ignore[method-assign]

                old_home = os.environ.get("CODEX_HOME")
                os.environ["CODEX_HOME"] = str(root / "wrong-home")
                try:
                    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec):
                        await client.start()
                    status = client.status_snapshot()
                    return captured, status
                finally:
                    await client.stop()
                    storage.close()
                    if old_home is None:
                        os.environ.pop("CODEX_HOME", None)
                    else:
                        os.environ["CODEX_HOME"] = old_home

        captured, status = asyncio.run(scenario())
        kwargs = captured["kwargs"]
        self.assertIsInstance(kwargs, dict)
        env = kwargs["env"]
        self.assertIsInstance(env, dict)
        self.assertEqual(str(status["codexHome"]), env["CODEX_HOME"])
        self.assertNotEqual(env["CODEX_HOME"], str(Path(status["codexHome"]).parent / "wrong-home"))
        self.assertEqual("app-server", captured["args"][1])
