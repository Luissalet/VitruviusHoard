"""Start an unchanged reference fixture inside the evaluation runtime."""

from pathlib import Path
import os
import shutil
import tarfile
import subprocess
import sys
import json

source = Path("/reference")
runtime = Path("/runtime")
runtime.mkdir()
for row in json.loads((source / "files.json").read_text()):
    relative = row["path"].split("/environment/reference/", 1)[1]
    target = runtime / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    oid = (row.get("lfs") or {}).get("oid") or row["oid"]
    shutil.copyfile(Path("/blobs") / oid, target)
for archive in list(runtime.rglob("*")):
    if not archive.name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
        continue
    with tarfile.open(archive) as package:
        package.extractall(archive.parent, filter="data")
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
clone = runtime / "clone"
if (clone / "package-lock.json").is_file() and not (
    runtime / "standalone/server.js"
).is_file():
    subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=clone, check=True)
    subprocess.run(["npm", "run", "build"], cwd=clone, check=True)
    standalone = clone / "dist/standalone"
    if not standalone.is_dir():
        standalone = clone / ".next/standalone"
    shutil.copytree(standalone, runtime / "standalone")
    for relative in ("public", ".next/static"):
        if (clone / relative).is_dir():
            shutil.copytree(
                clone / relative, runtime / "standalone" / relative, dirs_exist_ok=True
            )
compile_script = runtime / "compile.sh"
if compile_script.is_file():
    subprocess.run(["/bin/bash", str(compile_script)], check=True)
os.execv("/bin/bash", ["bash", str(runtime / "run.sh")])
