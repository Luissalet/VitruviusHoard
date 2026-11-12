"""Materialize immutable benchmark stimuli and own their temporary local processes.

Only reference content is downloaded. Neither solutions nor hidden tests enter the
reconstruction input. Vitruvius runs and scores the candidate through RemakeRunner.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import httpx
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from urllib.request import Request, urlopen
from string import Template

from ..hoard_link.atomic import write_json_atomic


class Cancelled(Exception):
    pass


_cooldown_lock = threading.Lock()
_cooldown_until = 0.0
_blob_locks = {}


def retry_pause(headers):
    value = headers.get("Retry-After", "")
    if value.isdigit():
        return float(value)
    if value:
        try:
            return max(
                0,
                (
                    parsedate_to_datetime(value) - datetime.now(timezone.utc)
                ).total_seconds(),
            )
        except (ValueError, TypeError):
            pass
    reset = re.search(r"(?:^|;)\s*t=(\d+)", headers.get("RateLimit", ""))
    return float(reset[1]) if reset else 60


def fetch(url, cancel, client=None):
    global _cooldown_until
    for attempt in range(3):
        with _cooldown_lock:
            delay = max(0, _cooldown_until - time.monotonic())
        if delay and cancel.wait(delay):
            raise Cancelled()
        if cancel.is_set():
            raise Cancelled()
        try:
            if client is not None:
                response = client.get(url)
                response.raise_for_status()
                return response.content, response.headers
            with urlopen(
                Request(url, headers={"User-Agent": "Vitruvius-evaluation/1"}),
                timeout=60,
            ) as response:
                return response.read(), response.headers
        except (OSError, httpx.HTTPError) as error:
            if attempt == 2:
                raise
            response = getattr(error, "response", error)
            status = getattr(response, "status_code", getattr(response, "code", None))
            if status == 429:
                pause = retry_pause(response.headers)
                with _cooldown_lock:
                    _cooldown_until = max(_cooldown_until, time.monotonic() + pause)
                continue
            if cancel.wait(attempt + 1):
                raise Cancelled()


def file_hash(path, row):
    if row.get("lfs"):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest == row["lfs"]["oid"]
    data = path.read_bytes()
    return (
        hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        == row["oid"]
    )


def prepare(base, corpus, task_id, cancel, *, materialize=True):
    """Keep downloaded bytes and their original hashes beside a pinned revision."""
    root = Path(base) / "references" / corpus["revision"] / task_id
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "files.json"
    prefix = f"tasks/{task_id}/environment/reference/"
    if manifest.is_file():
        rows = json.loads(manifest.read_text(encoding="utf8"))
    else:
        url = (
            f"https://huggingface.co/api/datasets/{corpus['dataset']}/tree/"
            f"{corpus['revision']}/{prefix.rstrip('/')}?recursive=true&limit=1000"
        )
        rows = []
        while url:
            data, headers = fetch(url, cancel)
            rows.extend(row for row in json.loads(data) if row["type"] == "file")
            match = re.search(r'<([^>]+)>; rel="next"', headers.get("Link", ""))
            url = match[1] if match else None
        if not rows:
            raise ValueError("Reference download contained no files")
        write_json_atomic(manifest, rows)

    def download(row):
        relative = row["path"].removeprefix(prefix)
        member = PurePosixPath(relative)
        if (
            not row["path"].startswith(prefix)
            or member.is_absolute()
            or ".." in member.parts
            or "\\" in relative
            or PureWindowsPath(relative).drive
        ):
            raise ValueError("Invalid reference member path")
        path = root / "source" / relative
        oid = (row.get("lfs") or {}).get("oid") or row["oid"]
        blob = Path(base) / "blobs" / oid
        with _blob_locks.setdefault(str(blob), threading.Lock()):
            valid = (
                path.is_file()
                and path.stat().st_size == row["size"]
                and file_hash(path, row)
            )
            if not blob.is_file() or not file_hash(blob, row):
                blob.parent.mkdir(parents=True, exist_ok=True)
                temporary = blob.with_suffix(".part")
                if valid:
                    shutil.copyfile(path, temporary)
                else:
                    url = (
                        f"https://huggingface.co/datasets/{corpus['dataset']}/resolve/"
                        f"{corpus['revision']}/{quote(row['path'], safe='/')}"
                    )
                    data, _ = fetch(url, cancel, client)
                    temporary.write_bytes(data)
                if temporary.stat().st_size != row["size"] or not file_hash(
                    temporary, row
                ):
                    temporary.unlink()
                    raise ValueError(f"Reference checksum mismatch for {relative}")
                temporary.replace(blob)
            if not valid and materialize:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(blob, path)

    with httpx.Client(timeout=60, follow_redirects=True, trust_env=False) as client:
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(download, rows))
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    source = root / "source"
    # Original fixture archives retain their own relative root paths.
    for archive in (
        [] if os.name == "nt" or not materialize else list(source.rglob("*"))
    ):
        if not archive.name.endswith(
            (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")
        ):
            continue
        marker = archive.with_name(archive.name + ".unpacked")
        if not marker.exists():
            with tarfile.open(archive) as package:
                package.extractall(archive.parent, filter="data")
            marker.touch()
    return source, {
        "sha256": digest,
        "files": len(rows),
        "bytes": sum(r["size"] for r in rows),
    }


def command(source):
    """Use the corpus's source entry directly, without its orchestration CLI."""
    entry = source / "harbor_entry.py"
    if entry.is_file():
        return [sys.executable, str(entry)]
    entry = source / "clone" / "harbor_entry.py"
    if entry.is_file():
        return [sys.executable, str(entry)]
    server = source / "standalone" / "server.js"
    bootstrap = source / "runtime-support" / "websitebench-bootstrap.mjs"
    if server.is_file() and bootstrap.is_file():
        args = [shutil.which("node") or "node", "--import", bootstrap.as_uri()]
        migrate = source / "runtime-support" / "websitebench-migrate.mjs"
        if migrate.is_file():
            args.extend(["--import", migrate.as_uri()])
        return args + [str(server)]
    raise ValueError("Reference has no supported native entry point")


def verify_entry(url):
    # A healthy backend can still have a broken entry route. An HTTP error page
    # must never become the benchmark's reference composition.
    with urlopen(url + "/", timeout=15) as response:
        if response.status != 200:
            raise ValueError(f"Reference entry returned HTTP {response.status}")


@contextmanager
def running(source, state, log_path, cancel):
    """Fresh state per run, loopback only, always stop the owned reference."""
    state.mkdir(parents=True, exist_ok=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {
        **os.environ,
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "DATA_DIR": str(state.resolve()),
        "SEED": "0",
        "TZ": "UTC",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "WEBSITEBENCH_DATA_DIR": str(state.resolve()),
        "WEBSITEBENCH_LOCAL_HTTP_COOKIE": "1",
        "WEBSITEBENCH_PAYMENT_PROFILE": "local-sandbox",
        "WEBSITEBENCH_SITE_BACKEND_DATABASE": str(state.resolve() / "site.sqlite3"),
        "WEBSITEBENCH_SITE_BACKEND_RUNTIME": str(source / "backend" / "runtime.json"),
        "PYTHONPATH": os.pathsep.join([str(source / "vendor"), str(source / "clone")]),
    }
    # Read the stimulus's literal environment declarations. This does not run a
    # shell or interpret commands from its launcher.
    launcher = source / "run.sh"
    if launcher.is_file():
        values = {**env, "root": str(source), "DATA_DIR": str(state.resolve())}
        for key, value in re.findall(
            r"^export ([A-Z_]+)=(.+)$", launcher.read_text(encoding="utf8"), re.M
        ):
            env[key] = Template(value.strip().strip("\"'")).safe_substitute(values)
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command(source),
            cwd=source,
            env=env,
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(120):
                if cancel.is_set():
                    raise Cancelled()
                if process.poll() is not None:
                    raise ValueError(
                        "Reference exited. "
                        + log_path.read_text(encoding="utf8", errors="replace")[-2500:]
                    )
                try:
                    with urlopen(url + "/healthz", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                cancel.wait(0.25)
            else:
                raise ValueError("Reference health check timed out")
            verify_entry(url)
            yield url
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
