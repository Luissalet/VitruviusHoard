"""Start Vitruvius's Hoard on a free port and open the browser (Windows: os.startfile)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vitruvius_hoard.config import Config  # noqa: E402
from vitruvius_hoard.hoard_link import net, proc  # noqa: E402


def main() -> int:
    config = Config.from_env()
    port = config.port if config.port_strict else net.find_available_port(config.port)
    url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "VITRUVIUS_PORT": str(port), "PORT_STRICT": "1", "HOARD_NO_BROWSER": "1"}
    child = proc.popen([sys.executable, "-m", "vitruvius_hoard"], cwd=ROOT, env=env)
    if net.wait_healthy(url, "vitruvius-hoard", timeout=30.0):
        print(f"Opening {url}", flush=True)
        if not net.open_in_browser(url):
            print(f"Open {url} in your browser.")
    elif child.poll() is not None:
        return child.returncode or 1
    try:
        return child.wait()
    except KeyboardInterrupt:
        proc.kill_tree(child)
        return 0


if __name__ == "__main__":
    sys.exit(main())
