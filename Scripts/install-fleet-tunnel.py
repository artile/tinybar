#!/usr/bin/env python3
"""Install this user's persistent SSH tunnel to the loopback limits service."""

import argparse
import os
from pathlib import Path
import plistlib
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ssh-host", default="vps")
args = parser.parse_args()
label = "io.tao.tinybar.fleet-tunnel"
home = Path.home()
agents = home / "Library/LaunchAgents"
logs = home / "Library/Logs/Tinybar Fleet"
agents.mkdir(parents=True, exist_ok=True)
logs.mkdir(parents=True, exist_ok=True)
path = agents / (label + ".plist")
domain = f"gui/{os.getuid()}"
if path.exists():
    subprocess.run(["/bin/launchctl", "bootout", domain, str(path)], check=False, capture_output=True)
with path.open("wb") as output:
    plistlib.dump({"Label": label, "ProgramArguments": [
        "/usr/bin/ssh", "-N", "-T", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "-o", "ConnectTimeout=10",
        "-L", "127.0.0.1:18767:127.0.0.1:18767", args.ssh_host],
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 30,
        "StandardErrorPath": str(logs / "tunnel.log"),
        "StandardOutPath": str(logs / "tunnel.log")}, output)
path.chmod(0o600)
subprocess.run(["/bin/launchctl", "bootstrap", domain, str(path)], check=True)
print(f"Installed {label}; local account service: http://127.0.0.1:18767")
