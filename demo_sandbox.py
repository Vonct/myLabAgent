from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parent
MAX_STDOUT_CHARS = 4000


def safe_console(text: str) -> str:
    return text.encode("unicode_escape").decode("ascii")


@dataclass
class SandboxRequest:
    trace_id: str
    action: str
    args: dict[str, Any]


@dataclass
class SandboxResponse:
    ok: bool
    trace_id: str
    stage: str
    data: dict[str, Any]
    error: str = ""


class DemoSandbox:
    """A minimal sandbox demo based on fixed actions, not arbitrary scripts."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.allowed_actions = {
            "list_dir",
            "read_text_head",
            "python_version",
        }

    def execute(self, action: str, args: dict[str, Any] | None = None) -> SandboxResponse:
        request = SandboxRequest(
            trace_id=uuid.uuid4().hex[:12],
            action=action,
            args=args or {},
        )
        print(f"[parent] request={json.dumps(asdict(request), ensure_ascii=False)}")

        allowed, normalized_args, reason = self._authorize(request)
        if not allowed:
            response = SandboxResponse(
                ok=False,
                trace_id=request.trace_id,
                stage="parent_authorize",
                data={},
                error=reason,
            )
            print(f"[parent] blocked reason={reason}")
            return response

        payload = {
            "trace_id": request.trace_id,
            "action": request.action,
            "args": normalized_args,
            "root": str(self.root),
        }
        cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", json.dumps(payload, ensure_ascii=False)]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=8,
            shell=False,
            cwd=str(self.root),
            env=self._child_env(),
        )

        if proc.stderr.strip():
            print(f"[parent] worker-stderr={safe_console(proc.stderr.strip())}")

        if proc.returncode != 0:
            return SandboxResponse(
                ok=False,
                trace_id=request.trace_id,
                stage="parent_spawn",
                data={},
                error=f"worker exited with code {proc.returncode}",
            )

        raw_stdout = proc.stdout.strip()
        if len(raw_stdout) > MAX_STDOUT_CHARS:
            raw_stdout = raw_stdout[:MAX_STDOUT_CHARS] + "...(truncated)"
        print(f"[parent] worker-stdout={safe_console(raw_stdout)}")

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return SandboxResponse(
                ok=False,
                trace_id=request.trace_id,
                stage="parent_decode",
                data={"stdout": raw_stdout},
                error=f"invalid worker json: {exc}",
            )

        return SandboxResponse(**result)

    def _authorize(self, request: SandboxRequest) -> tuple[bool, dict[str, Any], str]:
        if request.action not in self.allowed_actions:
            return False, {}, f"action `{request.action}` is not in the allowlist"

        normalized_args = dict(request.args)
        if request.action in {"list_dir", "read_text_head"}:
            relative = str(request.args.get("path", ".")).strip() or "."
            target = self._resolve_inside_root(relative)
            if target is None:
                return False, {}, f"path `{relative}` escapes workspace root"
            normalized_args["path"] = str(target)

        if request.action == "read_text_head":
            lines = int(request.args.get("lines", 20))
            normalized_args["lines"] = max(1, min(lines, 50))

        return True, normalized_args, ""

    def _resolve_inside_root(self, user_path: str) -> Path | None:
        candidate = Path(user_path)
        full = candidate.resolve() if candidate.is_absolute() else (self.root / candidate).resolve()
        try:
            full.relative_to(self.root)
        except ValueError:
            return None
        return full

    def _child_env(self) -> dict[str, str]:
        keep = {"SystemRoot", "COMSPEC", "PATH", "PATHEXT", "WINDIR", "PYTHONIOENCODING"}
        env = {key: value for key, value in os.environ.items() if key in keep}
        env["PYTHONIOENCODING"] = "utf-8"
        return env


def run_worker(raw_payload: str) -> int:
    try:
        payload = json.loads(raw_payload)
        root = Path(payload["root"]).resolve()
        request = SandboxRequest(
            trace_id=payload["trace_id"],
            action=payload["action"],
            args=payload["args"],
        )
        sandbox = DemoSandbox(root)
        allowed, normalized_args, reason = sandbox._authorize(request)
        if not allowed:
            response = SandboxResponse(
                ok=False,
                trace_id=request.trace_id,
                stage="worker_authorize",
                data={},
                error=reason,
            )
        else:
            response = handle_action(root, request.trace_id, request.action, normalized_args)
    except Exception as exc:
        response = SandboxResponse(
            ok=False,
            trace_id="unknown",
            stage="worker_crash",
            data={},
            error=str(exc),
        )

    sys.stdout.write(json.dumps(asdict(response), ensure_ascii=False))
    return 0


def handle_action(root: Path, trace_id: str, action: str, args: dict[str, Any]) -> SandboxResponse:
    if action == "list_dir":
        target = Path(args["path"])
        entries = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:20]:
            entries.append(
                {
                    "name": item.name,
                    "kind": "dir" if item.is_dir() else "file",
                }
            )
        return SandboxResponse(
            ok=True,
            trace_id=trace_id,
            stage="worker_action",
            data={
                "action": action,
                "root": str(root),
                "path": str(target),
                "entries": entries,
            },
        )

    if action == "read_text_head":
        target = Path(args["path"])
        lines = int(args["lines"])
        content = target.read_text(encoding="utf-8", errors="replace").splitlines()
        head = "\n".join(content[:lines])
        return SandboxResponse(
            ok=True,
            trace_id=trace_id,
            stage="worker_action",
            data={
                "action": action,
                "path": str(target),
                "lines": lines,
                "preview": head,
            },
        )

    if action == "python_version":
        proc = subprocess.run(
            [sys.executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            shell=False,
            cwd=str(root),
        )
        version_text = (proc.stdout or proc.stderr).strip()
        return SandboxResponse(
            ok=True,
            trace_id=trace_id,
            stage="worker_action",
            data={
                "action": action,
                "argv": [sys.executable, "--version"],
                "returncode": proc.returncode,
                "stdout": version_text,
            },
        )

    return SandboxResponse(
        ok=False,
        trace_id=trace_id,
        stage="worker_action",
        data={},
        error=f"unknown action `{action}`",
    )


def print_result(title: str, response: SandboxResponse) -> None:
    print(f"\n=== {title} ===")
    print(safe_console(json.dumps(asdict(response), ensure_ascii=False, indent=2)))


def run_demo() -> int:
    sandbox = DemoSandbox(WORKSPACE_ROOT)

    print("demo sandbox root:", WORKSPACE_ROOT)
    print("data flow: request -> parent authorize -> worker subprocess -> json response")

    print_result(
        "allow: list current dir",
        sandbox.execute("list_dir", {"path": "."}),
    )
    print_result(
        "allow: read README head",
        sandbox.execute("read_text_head", {"path": "README.md", "lines": 8}),
    )
    print_result(
        "allow: fixed command python --version",
        sandbox.execute("python_version", {}),
    )
    print_result(
        "block: path escape",
        sandbox.execute("read_text_head", {"path": "..\\README.md", "lines": 5}),
    )
    print_result(
        "block: arbitrary action",
        sandbox.execute("run_anything", {"cmd": "whoami"}),
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal sandbox demo")
    parser.add_argument("--worker", help="internal worker mode", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.worker is not None:
        return run_worker(args.worker)
    return run_demo()


if __name__ == "__main__":
    raise SystemExit(main())
