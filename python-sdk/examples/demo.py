"""A short, non-interactive walkthrough; validate_full.py covers the complete workflow."""

import os
import time

from devbox import DevBox, DevBoxError


def main() -> None:
    name = os.getenv("DEVBOX_TEST_TEMPLATE", "default")
    with DevBox() as client:
        templates = client.templates.list()
        template = next(
            (item for item in templates if name in (item.name, item.template_id, *item.aliases)),
            None,
        )
        if template is None:
            raise ValueError(f"template {name!r} is not available")
        print(f"[1/7] Template selected | name={template.name}, build={template.build_id}")
        with client.sandboxes.create(
            template.template_id,
            build_id=template.build_id,
            timeout=300,
            envs={"DEMO_MESSAGE": "hello from DevBox"},
            metadata={"example": "python-sdk-demo"},
        ) as sandbox:
            info = sandbox.get_info()
            print(f"[2/7] Sandbox created | id={sandbox.sandbox_id}, state={info.state.value}")
            print(f"      expires_at={info.end_at}")

            result = sandbox.commands.run('printf "%s" "$DEMO_MESSAGE"')
            print(f"[3/7] Command executed | exit={result.exit_code}, stdout={result.stdout!r}")

            path = "/tmp/devbox-demo.txt"
            sandbox.files.write(path, "This file must survive a pause.")
            content = sandbox.files.read(path)
            print(f"[4/7] File written and read | path={path}, content={content!r}")

            process = sandbox.commands.run("cat", background=True, stdin=True, timeout=10)
            process.send_stdin("background input received\n")
            process.close_stdin()
            result = process.wait()
            print(
                f"[5/7] Background stdin -> EOF -> wait | pid={result.pid}"
                f", stdout={result.stdout!r}"
            )

            started = time.monotonic()
            sandbox.pause()
            print(
                f"[6/7] Paused | state={sandbox.get_info().state.value}"
                f", elapsed={time.monotonic() - started:.3f}s"
            )
            sandbox.resume(timeout=300)
            restored = sandbox.files.read(path)
            if restored != content:
                raise AssertionError("file changed after resume")
            print(f"[7/7] Resumed | same sandbox={sandbox.sandbox_id}, file preserved={restored!r}")
        print("Demo completed | remote sandbox deleted, local connections closed")


if __name__ == "__main__":
    try:
        main()
    except (DevBoxError, ValueError) as error:
        raise SystemExit(f"DevBox SDK demo failed | {error}") from None
