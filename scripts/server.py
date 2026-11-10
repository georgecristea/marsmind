#!/usr/bin/env python3
"""Launch the vendored TM app server — LAN-visible BY DEFAULT.

Standing requirement: the practice server must always be reachable from
the local network (a seat may play from another machine on the LAN), with
zero per-launch fiddling. This launcher pins
HOST=0.0.0.0 explicitly (the vendor reads the env var; an unset HOST
merely *happens* to bind all interfaces today) and prints the LAN URL.

    python3 scripts/server.py           # start (refuses if already up)
    python3 scripts/server.py status    # bind + LAN URL + reachability
"""
import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "terraforming-mars"
LOG = ROOT / "private" / "server.log"


class AlreadyRunning(Exception):
    pass


def server_env(base: dict, port: int = 8080) -> dict:
    env = dict(base)
    env["HOST"] = "0.0.0.0"          # the guarantee, not an accident
    env["PORT"] = str(port)
    return env


def lan_url(ip: str, port: int) -> str:
    return f"http://{ip}:{port}"


def lan_ip() -> str | None:
    for dev in ("en0", "en1"):
        r = subprocess.run(["ipconfig", "getifaddr", dev],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def _port_listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start(port: int = 8080, port_check=_port_listening, spawn=None) -> str:
    if port_check(port):
        raise AlreadyRunning(
            f"port {port} already serving — use 'status'; never start twice")
    if spawn is None:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        def spawn(env):
            with open(LOG, "ab") as log:
                subprocess.Popen(
                    ["node", "build/src/server/server.js"], cwd=VENDOR,
                    env=env, stdout=log, stderr=log,
                    start_new_session=True)
    spawn(server_env(dict(os.environ), port=port))
    ip = lan_ip() or "<lan-ip-unknown>"
    return (f"server starting (log: {LOG})\n"
            f"  local: http://localhost:{port}\n"
            f"  LAN:   {lan_url(ip, port)}   ← openclaw uses this")


def status(port: int = 8080) -> str:
    up = _port_listening(port)
    ip = lan_ip()
    lines = [f"port {port}: {'LISTENING' if up else 'not listening'}"]
    if up and ip:
        with socket.socket() as s:
            s.settimeout(1.0)
            lan_ok = s.connect_ex((ip, port)) == 0
        lines.append(f"LAN {lan_url(ip, port)}: "
                     f"{'reachable ✓' if lan_ok else 'NOT reachable — check firewall/bind'}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", nargs="?", default="start",
                    choices=("start", "status"))
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()
    try:
        print(start(a.port) if a.cmd == "start" else status(a.port))
    except AlreadyRunning as e:
        print(f"NOT STARTED: {e}", file=sys.stderr)
        print(status(a.port))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
