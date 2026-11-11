"""Start an unchanged reference fixture inside the evaluation runtime."""

from pathlib import Path
import os
import shutil
import tarfile
import subprocess
import sys

source = Path("/reference")
runtime = Path("/runtime")
shutil.copytree(source, runtime)
for archive in runtime.rglob("*.tar"):
    target = archive.with_suffix("")
    target.mkdir(exist_ok=True)
    with tarfile.open(archive) as package:
        package.extractall(target, filter="data")
for path in runtime.rglob("*.sh"):
    path.chmod(0o755)
lock = runtime / "vendor.requirements.lock"
if lock.is_file():
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            "/wheels",
            "--no-deps",
            "--require-hashes",
            "--target",
            str(runtime / "vendor"),
            "-r",
            str(lock),
        ],
        check=True,
    )
os.chdir(runtime)
os.execv("/bin/bash", ["bash", str(runtime / "run.sh")])
