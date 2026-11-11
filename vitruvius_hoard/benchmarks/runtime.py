"""One Linux reference at a time, with an owned process and fresh state."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen
import uuid

from .references import Cancelled, verify_entry

ROOT = Path(__file__).parent


def image_tag():
    digest = hashlib.sha256(
        b"".join(
            (ROOT / name).read_bytes()
            for name in (
                "Reference.Dockerfile",
                "container_entry.py",
                "build_runtime.py",
                "reference-dependencies.json",
            )
        )
    ).hexdigest()
    return "vitruvius-reference:" + digest[:16]


def prepare(cancel, folder, kind):
    if kind == "native":
        return {"kind": "native"}
    tag = image_tag()
    inspect = subprocess.run(
        ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if inspect.returncode:
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "runtime-build.log").open("wb") as log:
            process = subprocess.Popen(
                [
                    "docker",
                    "build",
                    "--tag",
                    tag,
                    "--file",
                    str(ROOT / "Reference.Dockerfile"),
                    str(ROOT),
                ],
                stdout=log,
                stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                while process.poll() is None:
                    if cancel.wait(0.25):
                        raise Cancelled()
                if process.returncode:
                    raise ValueError(
                        "Reference runtime build failed. "
                        + (folder / "runtime-build.log").read_text(errors="replace")[
                            -3000:
                        ]
                    )
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
        inspect = subprocess.run(
            ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        inspect.check_returncode()
    return {"kind": "container", "image": tag, "image_id": inspect.stdout.strip()}


@contextmanager
def running(source, state, log_path, cancel):
    name = "vitruvius-reference-" + uuid.uuid4().hex[:12]
    state.mkdir(parents=True, exist_ok=True)
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--publish",
        "127.0.0.1::8080",
        "--mount",
        f"type=bind,source={source.resolve()},target=/reference,readonly",
        "--mount",
        f"type=bind,source={state.resolve()},target=/state",
        image_tag(),
    ]
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            url = None
            for _ in range(240):
                if cancel.is_set():
                    raise Cancelled()
                if process.poll() is not None:
                    raise ValueError(
                        "Reference exited. "
                        + log_path.read_text(errors="replace")[-3000:]
                    )
                if url is None:
                    result = subprocess.run(
                        ["docker", "port", name, "8080/tcp"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        url = "http://" + result.stdout.strip()
                if url:
                    try:
                        with urlopen(url + "/healthz", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                cancel.wait(0.25)
            else:
                raise ValueError("Reference runtime health check timed out")
            verify_entry(url)
            yield url
        finally:
            subprocess.run(
                ["docker", "stop", "--time", "3", name], capture_output=True, timeout=15
            )
            subprocess.run(
                ["docker", "rm", "--force", name], capture_output=True, timeout=15
            )
            process.wait(timeout=15)
