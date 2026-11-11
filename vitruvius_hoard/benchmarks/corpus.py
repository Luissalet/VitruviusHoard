"""Read-only corpus discovery. Importing this module performs no network or process work."""

import hashlib
import json
from pathlib import Path
import platform
from importlib.metadata import PackageNotFoundError, version

ROOT = Path(__file__).parent


def catalog():
    raw = (ROOT / "corpus.json").read_bytes()
    return {**json.loads(raw), "manifest_sha256": hashlib.sha256(raw).hexdigest()}


def implementation():
    root = ROOT.parent
    paths = [root / name for name in ("remake.py", "parity.py", "browser.py")]
    paths += (
        sorted(ROOT.glob("*.py"))
        + sorted(ROOT.glob("*.json"))
        + [ROOT / "Reference.Dockerfile"]
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(
            path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes()
        )
    return digest.hexdigest()


def environment():
    packages = {}
    for name in (
        "playwright",
        "pillow",
        "fastapi",
        "starlette",
        "pydantic",
        "uvicorn",
        "jinja2",
        "tzdata",
    ):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {
        "python": platform.python_version(),
        "system": platform.system(),
        "packages": packages,
    }
