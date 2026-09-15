"""Start local Telegram Bot API (2 GB) then Spotigram. Restarts the API if it dies."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
API_EXE = ROOT / "bin" / "botapi" / "telegram-bot-api.exe"
API_DIR = ROOT / "data" / "bot-api"
API_LOG = ROOT / "data" / "bot-api-server.log"
API_PORT = 8081


def _wait_port(port: int, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.4)
    raise SystemExit(f"telegram-bot-api did not open port {port}")


def spawn_api() -> subprocess.Popen:
    API_DIR.mkdir(parents=True, exist_ok=True)
    if not API_EXE.exists():
        raise SystemExit(f"missing {API_EXE}")
    log = open(API_LOG, "ab", buffering=0)
    proc = subprocess.Popen(
        [
            str(API_EXE),
            "--local",
            f"--http-port={API_PORT}",
            f"--dir={API_DIR}",
            "--verbosity=1",
        ],
        cwd=str(ROOT),
        stdout=log,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    return proc


def watch_api(holder: dict) -> None:
    while True:
        proc: subprocess.Popen = holder["proc"]
        code = proc.poll()
        if code is not None:
            print(f"telegram-bot-api exited {code}; restarting", flush=True)
            time.sleep(1)
            holder["proc"] = spawn_api()
            try:
                _wait_port(API_PORT, timeout=30)
            except SystemExit as exc:
                print(exc, flush=True)
        time.sleep(2)


def main() -> None:
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    if not os.environ.get("TELEGRAM_API_ID") or not os.environ.get("TELEGRAM_API_HASH"):
        raise SystemExit("TELEGRAM_API_ID / TELEGRAM_API_HASH missing from .env")
    os.environ.setdefault("TELEGRAM_BOT_API_URL", f"http://127.0.0.1:{API_PORT}")
    sys.path.insert(0, str(ROOT / "src"))

    holder = {"proc": spawn_api()}
    _wait_port(API_PORT)
    print("local Bot API is up on 8081", flush=True)
    threading.Thread(target=watch_api, args=(holder,), daemon=True).start()

    from spotigram.bot import run

    run()


if __name__ == "__main__":
    main()
