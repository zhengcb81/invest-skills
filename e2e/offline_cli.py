"""Run an existing CLI with network disabled for offline fixture/E2E checks."""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys


def install_offline_guard() -> None:
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ.pop("REVENUE_ATTESTATION_PROVIDER", None)
    def deny_network(event, _args):
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind", "urllib.Request"}:
            raise RuntimeError("Network is disabled in the offline E2E process")
    sys.addaudithook(deny_network)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: offline_cli.py SCRIPT [CLI arguments]")
    target = Path(sys.argv[1]).resolve()
    sys.argv = [str(target), *sys.argv[2:]]
    install_offline_guard()
    sys.path.insert(0, str(target.parent))
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
