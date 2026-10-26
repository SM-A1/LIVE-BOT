from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.security.validators import valid_url

RUNNER = str(Path(__file__).resolve().parent.parent / "workers" / "script_runner.py")


@dataclass
class ScriptResult:
    actions: list[dict] = field(default_factory=list)
    error: str | None = None


def _limits(mem_bytes: int, cpu_s: int):
    def apply() -> None:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))  # script cannot fork/spawn
    return apply


class ScriptSandbox:
    """Runs user scripts in a separate, resource-limited Python process (never in the manager process)."""

    def __init__(self, timeout: float = 3.0, mem_mb: int = 256, concurrency: int = 2):
        self.timeout, self.mem = timeout, mem_mb * 1024 * 1024
        self._sem = asyncio.Semaphore(concurrency)

    async def run(self, code: str, ctx: dict) -> ScriptResult:
        if os.name != "posix":
            return ScriptResult(error="Sandbox is only available on Linux hosts.")
        async with self._sem:
            tmp = tempfile.mkdtemp(prefix="sbx-")
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-I", "-S", RUNNER,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd=tmp, env={}, start_new_session=True,
                    preexec_fn=_limits(self.mem, int(self.timeout) + 1))
                payload = json.dumps({"code": code, "ctx": ctx}).encode()
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(payload), self.timeout)
                except asyncio.TimeoutError:
                    return ScriptResult(error=f"Script timed out after {self.timeout:.0f}s")
                if not out:
                    return ScriptResult(error="Script was stopped (resource limit exceeded)")
                data = json.loads(out[:65536])
            except Exception:
                return ScriptResult(error="Script could not be executed")
            finally:
                if proc and proc.returncode is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await proc.wait()
                shutil.rmtree(tmp, ignore_errors=True)
        if not data.get("ok"):
            return ScriptResult(error=str(data.get("error", "Script error"))[:300])
        return ScriptResult(actions=self._clean(data.get("actions", [])))

    @staticmethod
    def _clean(actions) -> list[dict]:
        out = []
        for a in actions[:5]:
            if not isinstance(a, dict) or not isinstance(a.get("text"), str) or not a["text"].strip():
                continue
            item = {"op": "reply", "text": a["text"][:4096]}
            if a.get("op") == "reply_buttons":
                rows = [[(l, u) for l, u in row if isinstance(l, str) and isinstance(u, str) and valid_url(u)]
                        for row in a.get("rows", []) if isinstance(row, list)]
                rows = [r for r in rows if r]
                if rows:
                    item = {"op": "reply_buttons", "text": item["text"], "rows": rows}
            out.append(item)
        return out
