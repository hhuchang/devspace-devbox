from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from devbox import (
    AsyncDevBox,
    CommandExitError,
    CommandHandle,
    CommandResult,
    DevBox,
    NotFoundError,
    PtySize,
    Sandbox,
    SandboxInfo,
    SandboxLifecycle,
    SandboxState,
    TemplateInfo,
)
from devbox.config import ConnectionConfig

T = TypeVar("T")


class Validator:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.tests = 0
        self.started_at = time.monotonic()

    def verify(self, name: str, operation: Callable[[], T]) -> T | None:
        self.tests += 1
        started_at = time.monotonic()
        print(f"\nTEST {self.tests:02d} | {name}", flush=True)
        try:
            result = operation()
        except Exception as error:
            self.failures.append(name)
            print(
                f"FAIL {name} | {_seconds(started_at)}s | {type(error).__name__}: {error}",
                flush=True,
            )
            if error.__cause__ is not None:
                traceback.print_exception(type(error), error, error.__traceback__, file=sys.stdout)
            return None
        print(f"PASS {name} | {_seconds(started_at)}s", flush=True)
        return result

    def finish(self) -> None:
        passed = self.tests - len(self.failures)
        print(
            f"SUMMARY tests={self.tests} passed={passed} failed={len(self.failures)}"
            f" elapsed={_seconds(self.started_at)}s"
        )
        if self.failures:
            print(f"FAILED {', '.join(self.failures)}")
            raise SystemExit(1)


def main(*, lifecycle_only: bool = False) -> None:
    template = os.getenv("DEVBOX_TEST_TEMPLATE", "default").strip() or "default"
    validator = Validator()
    sandbox: Sandbox | None = None

    print(f"DevBox {'lifecycle' if lifecycle_only else 'full'} validation | template={template}")
    gateway_url = ConnectionConfig.resolve().gateway_url
    if gateway_url:
        print(f"gateway={gateway_url}")
    if gateway_url and "{tunnel_id}" not in gateway_url:
        raise ValueError(
            "Validation requires the created sandbox: unset DEVBOX_GATEWAY_URL or use {tunnel_id}"
        )

    client = DevBox()
    try:
        _section("Templates", "List available templates and select a concrete build")
        selected = validator.verify("templates.list", lambda: _select_template(client, template))
        if selected is None:
            validator.finish()
            return
        _section(
            "Create sandbox", f"Start template={template!r}, timeout=300s, with an isolated runtime"
        )
        sandbox = validator.verify(
            "sandbox.create",
            lambda: _step(
                "sandboxes.create(envs=..., lifecycle={on_timeout:'pause', auto_resume:True})",
                lambda: client.sandboxes.create(
                    selected.template_id,
                    build_id=selected.build_id,
                    timeout=300,
                    envs={"DEVBOX_SDK_ENV": "created-731"},
                    metadata={"sdk_validation": "python"},
                    lifecycle=SandboxLifecycle(on_timeout="pause", auto_resume=True),
                ),
            ),
        )
        if sandbox is None:
            print("STOP sandbox creation failed; runtime validation cannot continue")
        else:
            print(f"sandbox_id={sandbox.sandbox_id}")
            if not lifecycle_only:
                validate_sandbox(client, sandbox, validator)
            validate_lifecycle(client, sandbox, validator)
    finally:
        if sandbox is not None:
            _section("Cleanup", "Delete the remote sandbox and close local connections")
            validator.verify("sandbox.delete", lambda: _step("sandbox.kill()", sandbox.kill))
            sandbox.close()
        client.close()

    if sandbox is not None:
        with DevBox() as expiry_client:
            validator.verify(
                "lifecycle.timeout_kill", lambda: _validate_expiry(expiry_client, selected)
            )
    validator.finish()


def _select_template(client: DevBox, name: str) -> TemplateInfo:
    templates = _step("templates.list()", client.templates.list)
    for item in templates:
        print(
            f"    {item.name} | id={item.template_id} | build={item.build_id}"
            f" | aliases={','.join(item.aliases)} | cpu={item.cpu_count}"
            f" | memory={item.memory_mb} MiB"
        )
    selected = next(
        (item for item in templates if name in (item.name, item.template_id, *item.aliases)), None
    )
    if selected is None:
        raise AssertionError(f"template {name!r} is not in the available catalog")
    print(f"    SELECT {selected.name} | build={selected.build_id}")
    return selected


def _validate_connect(client: DevBox, sandbox: Sandbox) -> None:
    connected = _step(
        f"sandboxes.connect({sandbox.sandbox_id!r}) | open a new SDK handle",
        lambda: client.sandboxes.connect(sandbox.sandbox_id),
    )
    try:
        _equal(connected.sandbox_id, sandbox.sandbox_id)
    finally:
        _step("connected.close() | keep the remote sandbox running", connected.close)


def validate_lifecycle(client: DevBox, sandbox: Sandbox, validator: Validator) -> None:
    _section(
        "Lifecycle", "Keep files, environment and the original process across pause and recovery"
    )
    path = f"/tmp/devbox-lifecycle-{uuid4().hex[:8]}"
    payload = bytes(range(256)) * 4096
    process: CommandHandle | None = None

    def prepare() -> None:
        nonlocal process
        _step(
            f"files.write({path!r}, <1 MiB>) | persistence proof",
            lambda: sandbox.files.write(path, payload),
        )
        process = _step(
            "commands.run('sleep 900', background=True)",
            lambda: sandbox.commands.run("sleep 900", background=True),
        )
        _step("process.disconnect() | keep the remote process alive", process.disconnect)

    def persistence() -> None:
        assert process is not None
        _equal(
            _step(
                "files.read_bytes() | compare all 1 MiB after recovery",
                lambda: sandbox.files.read_bytes(path),
            ),
            payload,
        )
        print("    CHECK file content: identical (1 MiB)", flush=True)
        running = _step("commands.list() | find the original running PID", sandbox.commands.list)
        _equal(any(item.pid == process.pid and item.running for item in running), True)
        print(f"    CHECK original process: pid={process.pid}, still running", flush=True)
        _validate_environment(sandbox)
        _equal(_step("sandbox.get_info()", sandbox.get_info).state, SandboxState.RUNNING)

    def deadlines() -> None:
        _step(
            "set_timeout(7200) | remaining lifetime becomes 2h (greater than 1h)",
            lambda: sandbox.set_timeout(7200),
        )
        extended = _deadline(sandbox, 7200)
        _step(
            "refresh(120) | must not shorten the existing 2h deadline", lambda: sandbox.refresh(120)
        )
        _equal(_step("get_info() | compare deadline", sandbox.get_info).end_at, extended)
        _step(
            "set_timeout(300) | explicitly shorten remaining lifetime to 5min",
            lambda: sandbox.set_timeout(300),
        )
        _deadline(sandbox, 300)
        _step(
            "refresh(600) | extend remaining lifetime to at least 10min",
            lambda: sandbox.refresh(600),
        )
        _deadline(sandbox, 600)

    def manual_resume() -> None:
        _step("sandbox.pause() | save the running instance", sandbox.pause)
        _equal(_step("get_info() | expect paused", sandbox.get_info).state, SandboxState.PAUSED)
        _step(
            "sandbox.resume(timeout=300) | restore this sandbox handle",
            lambda: sandbox.resume(timeout=300),
        )
        _deadline(sandbox, 300)
        persistence()

    def connect_resume() -> None:
        _step("sandbox.pause()", sandbox.pause)
        _step("sandbox.close() | close local connections, not the sandbox", sandbox.close)
        connected = _step(
            "sandboxes.connect(id, timeout=300) | Manager restores the paused sandbox",
            lambda: client.sandboxes.connect(sandbox.sandbox_id, timeout=300),
        )
        try:
            _equal(connected.sandbox_id, sandbox.sandbox_id)
            _equal(
                _step(
                    "connected.files.read_bytes() | same remote filesystem",
                    lambda: connected.files.read_bytes(path),
                ),
                payload,
            )
            _deadline(connected, 300)
        finally:
            _step("connected.close() | release the extra SDK handle", connected.close)
        persistence()

    def automatic_resume() -> None:
        _step(
            "set_timeout(10) | on_timeout=pause, auto_resume=True", lambda: sandbox.set_timeout(10)
        )
        _wait_for_state(sandbox, SandboxState.PAUSED)
        _step("sandbox.close() | force a fresh data-plane connection", sandbox.close)
        print("    FLOW SDK request -> Gateway -> Manager gRPC -> restored runtime", flush=True)
        print("    No explicit sandbox.resume() or sandboxes.connect() call follows.", flush=True)
        result = _step(
            "commands.run('printf gateway-wake-ok') | access the paused sandbox directly",
            lambda: sandbox.commands.run("printf gateway-wake-ok", timeout=90),
        )
        _expect_result(result, stdout="gateway-wake-ok", stderr="")
        persistence()

    for name, operation in (
        ("lifecycle.prepare", prepare),
        ("lifecycle.deadlines", deadlines),
        ("lifecycle.manual_resume", manual_resume),
        ("lifecycle.connect_resume", connect_resume),
        ("lifecycle.gateway_auto_resume", automatic_resume),
    ):
        failures = len(validator.failures)
        validator.verify(name, operation)
        if len(validator.failures) != failures:
            print("STOP dependent lifecycle steps; cleanup will still run", flush=True)
            return


def _deadline(sandbox: Sandbox, seconds: int) -> datetime:
    info = _step("sandbox.get_info() | read the real Manager deadline", sandbox.get_info)
    if info.end_at is None:
        raise AssertionError("Manager did not return an expiration time")
    remaining = (info.end_at - datetime.now(timezone.utc)).total_seconds()
    if not seconds - 15 <= remaining <= seconds + 5:
        raise AssertionError(f"expected about {seconds}s remaining, received {remaining:.1f}s")
    print(
        f"    CHECK remaining={remaining:.1f}s | expires_at={info.end_at.isoformat()}", flush=True
    )
    return info.end_at


def _wait_for_state(sandbox: Sandbox, expected: SandboxState) -> None:
    print(f"  WAIT Manager state={expected.value} | polling every 2s, maximum 90s", flush=True)
    started = time.monotonic()
    previous = ""
    while time.monotonic() - started < 90:
        try:
            state = sandbox.get_info().state
        except NotFoundError:
            if expected is not SandboxState.STOPPED:
                raise
            state = SandboxState.STOPPED
        if state.value != previous:
            print(f"    STATE {state.value} | elapsed={_seconds(started)}s", flush=True)
            previous = state.value
        if state is expected:
            return
        if state is SandboxState.FAILED:
            raise AssertionError("sandbox entered failed state")
        time.sleep(2)
    raise AssertionError(f"sandbox did not reach {expected.value} within 90s")


def _validate_expiry(client: DevBox, template: TemplateInfo) -> None:
    _section("Timeout cleanup", "A separate sandbox uses on_timeout=kill, not pause")
    sandbox = _step(
        "sandboxes.create(timeout=10, lifecycle=kill)",
        lambda: client.sandboxes.create(
            template.template_id, build_id=template.build_id, timeout=10
        ),
    )
    print(f"    sandbox_id={sandbox.sandbox_id}", flush=True)
    try:
        _wait_for_state(sandbox, SandboxState.STOPPED)
        _equal(_step("sandbox.is_running() | expect False", sandbox.is_running), False)
        _step("sandbox.kill() | cleanup is safe even after expiration", sandbox.kill)
    finally:
        try:
            sandbox.kill()
        finally:
            sandbox.close()


def validate_sandbox(client: DevBox, sandbox: Sandbox, validator: Validator) -> None:
    _section("Sandbox management", "Inspect the sandbox, list it and obtain a new SDK handle")
    validator.verify(
        "manager.get",
        lambda: _equal(
            _step("sandbox.get_info()", sandbox.get_info).sandbox_id, sandbox.sandbox_id
        ),
    )
    validator.verify(
        "manager.is_running",
        lambda: _equal(_step("sandbox.is_running()", sandbox.is_running), True),
    )
    validator.verify("manager.list", lambda: _validate_list(client, sandbox))
    validator.verify("manager.connect", lambda: _validate_connect(client, sandbox))
    runtime_ready = validator.verify("runtime.ready", lambda: _validate_runtime(sandbox))
    if runtime_ready is None:
        print("SKIP commands, filesystem, PTY and Git: runtime gateway is unavailable")
        return

    validator.verify("runtime.environment", lambda: _validate_environment(sandbox))

    validate_commands(sandbox, validator)
    validate_filesystem(sandbox, validator)
    validate_pty(sandbox, validator)
    validate_git(sandbox, validator)


def validate_commands(sandbox: Sandbox, validator: Validator) -> None:
    _section("Commands", "Capture stdout/stderr, run background jobs and send standard input")
    validator.verify("commands.foreground", lambda: _foreground_command(sandbox))
    validator.verify("commands.background", lambda: _background_command(sandbox))
    validator.verify("commands.stdin", lambda: _stdin_command(sandbox))
    validator.verify("commands.reconnect", lambda: _reconnect_command(sandbox))
    validator.verify("commands.streaming", lambda: _streaming_command(sandbox))
    validator.verify("commands.signal", lambda: _signal_command(sandbox))


def validate_filesystem(sandbox: Sandbox, validator: Validator) -> None:
    _section("Files", "Create, read, inspect, move, upload, download and remove files")
    root = f"/tmp/devbox-sdk-{uuid4().hex[:8]}"
    validator.verify("filesystem.basic", lambda: _filesystem_basic(sandbox, root))
    validator.verify("filesystem.transfer", lambda: _filesystem_transfer(sandbox, root))
    validator.verify(
        "filesystem.watch", lambda: asyncio.run(_filesystem_watch(sandbox.sandbox_id, root))
    )
    validator.verify(
        "filesystem.remove",
        lambda: _step(f"files.remove({root!r})", lambda: sandbox.files.remove(root)),
    )


def validate_pty(sandbox: Sandbox, validator: Validator) -> None:
    _section("Interactive terminal", "Start Bash, resize the terminal, send input and exit")

    def interaction() -> None:
        session = _step(
            "pty.start(rows=24, cols=80)", lambda: sandbox.pty.start(size=PtySize(rows=24, cols=80))
        )
        _step(
            f"pty.resize(pid={session.pid}, rows=30, cols=100)",
            lambda: sandbox.pty.resize(session.pid, PtySize(rows=30, cols=100)),
        )
        command = "printf '\\n__PTY_%s__\\n' \"$((19+23))\"; stty size; exit 7\n"
        _step(
            f"session.send_stdin({command!r}) | compute 42, inspect size, exit with code 7",
            lambda: session.send_stdin(command),
        )
        result = _step(
            "session.wait() | read terminal output until Bash exits",
            lambda: session.wait(check=False),
        )
        _validate_terminal_result(result)
        try:
            session.send_stdin("must-not-run\n")
        except RuntimeError:
            print("    completed session rejects further input", flush=True)
        else:
            raise AssertionError("completed terminal accepted input")

    validator.verify("pty.interaction", interaction)


def validate_git(sandbox: Sandbox, validator: Validator) -> None:
    _section("Git", "Initialize a repository, configure an author, stage and commit a file")
    repository = f"/tmp/devbox-sdk-git-{uuid4().hex[:8]}"

    def workflow() -> None:
        command = f"mkdir -p {repository} && git -C {repository} init -b main"
        _step(f"commands.run({command!r})", lambda: sandbox.commands.run(command))
        _step(
            "git.set_config(user.name='DevBox SDK')",
            lambda: sandbox.git.set_config(repository, "user.name", "DevBox SDK"),
        )
        _step(
            "git.set_config(user.email='sdk@devbox.local')",
            lambda: sandbox.git.set_config(repository, "user.email", "sdk@devbox.local"),
        )
        _step(
            "files.write(README.md, 'test\\n')",
            lambda: sandbox.files.write(f"{repository}/README.md", "test\n"),
        )
        _step("git.add() | stage changes", lambda: sandbox.git.add(repository))
        _step("git.commit('test commit')", lambda: sandbox.git.commit(repository, "test commit"))
        committed = _step(
            "git show HEAD:README.md | verify committed content, not just exit code",
            lambda: sandbox.commands.run(f"git -C {repository} show HEAD:README.md"),
        )
        _expect_result(committed, stdout="test\n", stderr="")
        result = _step(
            "git.status() | expect a clean working tree", lambda: sandbox.git.status(repository)
        )
        _equal(result.stdout.strip(), "## main")

    validator.verify("git.workflow", workflow)
    validator.verify(
        "git.remove",
        lambda: _step(f"files.remove({repository!r})", lambda: sandbox.files.remove(repository)),
    )


def _validate_terminal_result(result: CommandResult) -> None:
    lines = result.stdout.replace("\r", "").splitlines()
    _equal(result.exit_code, 7)
    _equal("__PTY_42__" in lines, True)
    _equal("30 100" in lines, True)


def _validate_environment(sandbox: Sandbox) -> None:
    command = 'printf "%s|%s" "$DEVBOX_ID" "$DEVBOX_SDK_ENV"'
    result = _step(
        f"commands.run({command!r}) | verify sandbox identity and create-time environment",
        lambda: sandbox.commands.run(command),
    )
    _expect_result(result, stdout=f"{sandbox.sandbox_id}|created-731", stderr="")


def _validate_list(client: DevBox, sandbox: Sandbox) -> None:
    page = _step("sandboxes.list(limit=100)", lambda: client.sandboxes.list(limit=100))
    print(f"    sandboxes={len(page.items)} | current sandbox must be present", flush=True)
    _equal(any(item.sandbox_id == sandbox.sandbox_id for item in page.items), True)


def _validate_runtime(sandbox: Sandbox) -> bool:
    result = _step(
        "commands.run('printf runtime-ready') | verify remote execution without readiness retries",
        lambda: sandbox.commands.run("printf runtime-ready"),
    )
    _expect_result(result, stdout="runtime-ready", stderr="")
    return True


def _foreground_command(sandbox: Sandbox) -> None:
    command = 'printf "$DEVBOX_TEST"; printf error-ok >&2'
    result = _step(
        f"commands.run({command!r}) | cwd=/tmp, DEVBOX_TEST=command-ok",
        lambda: sandbox.commands.run(
            command,
            envs={"DEVBOX_TEST": "command-ok"},
            cwd="/tmp",
        ),
    )
    _expect_result(result, stdout="command-ok", stderr="error-ok")

    python_command = 'python3 -c "print(40 + 2)"'
    result = _step(
        f"commands.run({python_command!r}) | execute Python",
        lambda: sandbox.commands.run(
            python_command,
            cwd="/tmp",
        ),
    )
    _expect_result(result, stdout="42\n", stderr="")

    failed = _step(
        "commands.run('printf partial; printf deliberate >&2; exit 7', check=False)",
        lambda: sandbox.commands.run("printf partial; printf deliberate >&2; exit 7", check=False),
    )
    _equal((failed.exit_code, failed.stdout, failed.stderr), (7, "partial", "deliberate"))


def _reconnect_command(sandbox: Sandbox) -> None:
    process = _step(
        "commands.run('read line; printf reconnected:%s \"$line\"', background=True, stdin=True)",
        lambda: sandbox.commands.run(
            'read line; printf reconnected:%s "$line"', background=True, stdin=True, timeout=10
        ),
    )
    _step("process.disconnect() | remote process stays alive", process.disconnect)
    attached = _step(
        f"commands.connect({process.pid})",
        lambda: sandbox.commands.connect(process.pid, timeout=10),
    )
    _step(r"attached.send_stdin('proof-731\n')", lambda: attached.send_stdin("proof-731\n"))
    _expect_result(
        _step("attached.wait() | verify output after reconnect", attached.wait),
        stdout="reconnected:proof-731",
        stderr="",
    )


def _background_command(sandbox: Sandbox) -> None:
    process = _step(
        "commands.run('sleep 1; printf background-ok', background=True, timeout=10)",
        lambda: sandbox.commands.run(
            "sleep 1; printf background-ok",
            background=True,
            timeout=10,
        ),
    )
    print(
        "    SDK returned a handle; the remote process can continue in the background", flush=True
    )
    result = _step(
        f"process.wait(pid={process.pid}) | wait for completion and collect output", process.wait
    )
    _expect_result(result, stdout="background-ok")


def _streaming_command(sandbox: Sandbox) -> None:
    chunks: list[str] = []

    def output(chunk: str) -> None:
        chunks.append(chunk)
        print(f"    STREAM stdout={chunk!r}", flush=True)

    result = _step(
        "commands.run(..., on_stdout=...) | receive output while the command is running",
        lambda: sandbox.commands.run(
            "printf 'step-1\\n'; sleep 1; printf 'step-2\\n'", on_stdout=output
        ),
    )
    _expect_result(result, stdout="step-1\nstep-2\n", stderr="")
    _equal("".join(chunks), result.stdout)


def _signal_command(sandbox: Sandbox) -> None:
    process = _step(
        "commands.run('sleep 60', background=True)",
        lambda: sandbox.commands.run("sleep 60", background=True),
    )
    try:
        _step(
            "process.send_signal('SIGTERM') | terminate only this process",
            lambda: process.send_signal("SIGTERM"),
        )
        result = _step(
            "process.wait(check=False) | collect the termination status",
            lambda: process.wait(check=False),
        )
        if result.exit_code == 0:
            raise AssertionError("terminated sleep reported a successful exit")
    finally:
        process.disconnect()


def _stdin_command(sandbox: Sandbox) -> None:
    process = _step(
        "commands.run('cat', background=True, stdin=True, timeout=10)",
        lambda: sandbox.commands.run("cat", background=True, stdin=True, timeout=10),
    )
    _step(r"process.send_stdin('stdin-ok\n')", lambda: process.send_stdin("stdin-ok\n"))
    _step("process.close_stdin() | send EOF so cat can finish", process.close_stdin)
    _expect_result(
        _step("process.wait() | collect the echoed input", process.wait), stdout="stdin-ok\n"
    )


def _filesystem_basic(sandbox: Sandbox, root: str) -> None:
    _step(f"files.make_dir({root!r})", lambda: sandbox.files.make_dir(root))
    path = f"{root}/input.txt"
    moved = f"{root}/output.txt"
    _step(f"files.write({path!r}, 'file-ok')", lambda: sandbox.files.write(path, "file-ok"))
    _equal(_step(f"files.read({path!r})", lambda: sandbox.files.read(path)), "file-ok")
    _equal(_step(f"files.stat({path!r}) | size in bytes", lambda: sandbox.files.stat(path).size), 7)
    _equal(_step(f"files.exists({path!r})", lambda: sandbox.files.exists(path)), True)
    entries = _step(f"files.list({root!r})", lambda: sandbox.files.list(root))
    print(f"    entries={[item.name for item in entries]}", flush=True)
    _equal(any(item.name == "input.txt" for item in entries), True)
    _step(f"files.move({path!r}, {moved!r})", lambda: sandbox.files.move(path, moved))
    _equal(_step(f"files.exists({moved!r})", lambda: sandbox.files.exists(moved)), True)


def _filesystem_transfer(sandbox: Sandbox, root: str) -> None:
    binary_path = f"{root}/binary.dat"
    binary = bytes(range(256)) * 4096
    _step(
        f"files.write({binary_path!r}, <1 MiB binary data>)",
        lambda: sandbox.files.write(binary_path, binary),
    )
    downloaded = _step(
        f"files.read_bytes({binary_path!r})", lambda: sandbox.files.read_bytes(binary_path)
    )
    if downloaded != binary:
        raise AssertionError("binary file content changed during transfer")
    print(f"    verified {len(binary)} bytes, including NUL and non-UTF-8 bytes", flush=True)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory, "source.txt")
        target = Path(directory, "target.txt")
        source.write_text("transfer-ok", encoding="utf-8")
        _step(
            f"files.upload({str(source)!r}, {root + '/transfer.txt'!r}) | content='transfer-ok'",
            lambda: sandbox.files.upload(source, f"{root}/transfer.txt"),
        )
        _step(
            f"files.download({root + '/transfer.txt'!r}, {str(target)!r})",
            lambda: sandbox.files.download(f"{root}/transfer.txt", target),
        )
        _equal(
            _step("Read downloaded local file", lambda: target.read_text(encoding="utf-8")),
            "transfer-ok",
        )


async def _filesystem_watch(sandbox_id: str, root: str) -> None:
    print("  DO async files.watch() | observe a real file change, maximum 10s", flush=True)
    async with AsyncDevBox() as client:
        sandbox = await client.sandboxes.connect(sandbox_id)
        events = sandbox.files.watch(root, include_entry=False)
        process = None
        try:
            process = await sandbox.commands.run(
                f"sleep 1; printf watch-ok > {root}/watch-proof.txt", background=True
            )

            async def observed() -> None:
                async for event in events:
                    print(f"    EVENT name={event.name!r} type={event.type!r}", flush=True)
                    if event.name == "watch-proof.txt":
                        return
                raise AssertionError("watch stream ended before the file change")

            await asyncio.wait_for(observed(), timeout=10)
            _equal(await sandbox.files.read(f"{root}/watch-proof.txt"), "watch-ok")
            result = await process.wait()
            _expect_result(result, stdout="", stderr="")
        finally:
            await events.aclose()
            if process is not None:
                await process.disconnect()
            await sandbox.close()
        print("    CHECK file change observed; watcher and async connections closed", flush=True)


def _section(name: str, description: str) -> None:
    print(f"\n=== {name} ===\n{description}", flush=True)


def _step(description: str, operation: Callable[[], T]) -> T:
    print(f"  DO {description}", flush=True)
    started = time.monotonic()
    try:
        result = operation()
    except CommandExitError as error:
        _command_output(error.result)
        raise
    print(f"    DONE | {_seconds(started)}s", flush=True)
    if isinstance(result, CommandResult):
        _command_output(result)
    elif isinstance(result, CommandHandle):
        print(f"    pid={result.pid}", flush=True)
    elif isinstance(result, SandboxInfo):
        print(
            f"    state={result.state.value} | template={result.template_id}"
            f" | end_at={result.end_at}",
            flush=True,
        )
    elif isinstance(result, (str, bool, int)):
        print(f"    result={result!r}", flush=True)
    elif isinstance(result, bytes):
        print(f"    bytes={len(result)} | content checked separately", flush=True)
    elif isinstance(result, (list, tuple)):
        print(f"    items={len(result)}", flush=True)
    return result


def _command_output(result: CommandResult) -> None:
    print(f"    pid={result.pid} | exit_code={result.exit_code}", flush=True)
    for name, raw in (("stdout", result.stdout), ("stderr", result.stderr)):
        # Show terminal text without executing ANSI/OSC control sequences in the demo console.
        value = _terminal_text(raw)
        print(f"    {name}:", flush=True)
        for line in value[:4000].splitlines() or ["(empty)"]:
            print(f"      {line}", flush=True)
        if len(value) > 4000:
            print(f"      ... truncated ({len(value)} characters total)", flush=True)


def _terminal_text(value: str) -> str:
    value = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", value)
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    return "".join(character for character in value if character in "\n\t" or ord(character) >= 32)


def _expect_result(
    result: CommandResult,
    *,
    stdout: str | None = None,
    stderr: str | None = None,
) -> None:
    _equal(result.exit_code, 0)
    if stdout is not None:
        _equal(result.stdout, stdout)
    if stderr is not None:
        _equal(result.stderr, stderr)


def _equal(actual: object, expected: object) -> None:
    if actual != expected:
        if isinstance(actual, bytes) and isinstance(expected, bytes):
            raise AssertionError(
                f"binary content mismatch: expected {len(expected)} bytes, received {len(actual)}"
            )
        raise AssertionError(f"expected {expected!r}, received {actual!r}")


def _seconds(started_at: float) -> str:
    return f"{time.monotonic() - started_at:.3f}"


if __name__ == "__main__":
    main()
