"""Cache the published reference dependency versions for offline stimulus startup."""

import json
from pathlib import Path
import subprocess
import sys

for requirement in json.loads(Path("/dependencies.json").read_text()):
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--no-deps",
            "--only-binary=:all:",
            "--dest",
            "/wheels",
            requirement,
        ],
        check=True,
    )
