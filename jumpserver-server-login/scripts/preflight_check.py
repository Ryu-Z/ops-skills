#!/usr/bin/env python3
"""Validate prerequisites for the Jumpserver automation skill."""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGIN_SCRIPT = ROOT / "scripts" / "login_jump.exp"


@dataclass
class Result:
    level: str
    name: str
    detail: str


def run(command: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def command_check(name: str, required: bool = True) -> Result:
    path = shutil.which(name)
    if path:
        return Result("OK", name, path)
    return Result("FAIL" if required else "WARN", name, "not found in PATH")


def check_login_script() -> Result:
    if not LOGIN_SCRIPT.exists():
        return Result("FAIL", "scripts/login_jump.exp", "missing")
    mode = LOGIN_SCRIPT.stat().st_mode
    if not mode & stat.S_IXUSR:
        return Result("FAIL", "scripts/login_jump.exp", f"not executable; run chmod +x {LOGIN_SCRIPT}")
    return Result("OK", "scripts/login_jump.exp", str(LOGIN_SCRIPT))


def check_pexpect() -> Result:
    if importlib.util.find_spec("pexpect"):
        return Result("OK", "python dependency pexpect", "available")
    return Result("FAIL", "python dependency pexpect", "missing; run python -m pip install -r requirements.txt")


def check_ssh_config(host: str) -> Result:
    config = Path.home() / ".ssh" / "config"
    if not config.exists():
        return Result("FAIL", f"ssh config Host {host}", "~/.ssh/config missing")

    block: dict[str, str] = {}
    in_host = False
    for raw_line in config.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        key, value = parts[0].lower(), parts[1].strip()
        if key == "host":
            patterns = value.split()
            in_host = host in patterns
            continue
        if in_host and key in {"hostname", "user", "port", "identityfile"} and key not in block:
            block[key] = value

    missing = [key for key in ("hostname", "user", "port", "identityfile") if not block.get(key)]
    placeholders = [
        key
        for key, value in block.items()
        if "<" in value or ">" in value or value.endswith(".example.com")
    ]
    if missing:
        return Result("FAIL", f"ssh config Host {host}", f"explicit block missing fields: {', '.join(missing)}")
    if placeholders:
        return Result("FAIL", f"ssh config Host {host}", f"placeholder fields: {', '.join(placeholders)}")

    completed = run(["ssh", "-G", host])
    if completed.returncode != 0:
        return Result("FAIL", f"ssh config Host {host}", "ssh -G failed")

    return Result("OK", f"ssh config Host {host}", "resolved")


def check_totp_code(profile: str) -> Result:
    completed = run(["totp", profile], timeout=10)
    if completed.returncode != 0:
        return Result("FAIL", f"totp {profile}", "unable to generate OTP")
    if not completed.stdout.strip():
        return Result("FAIL", f"totp {profile}", "empty OTP output")
    return Result("OK", f"totp {profile}", "generated OTP (hidden)")


def print_install_hint(name: str) -> None:
    system = platform.system().lower()
    machine = platform.machine().lower()
    print()
    if name == "expect":
        print("expect install examples:")
        print("  macOS: brew install expect")
        print("  Ubuntu/Debian: sudo apt-get update && sudo apt-get install -y expect")
        print("  RHEL/CentOS/Rocky/Amazon Linux: sudo dnf install -y expect")
        print("  Windows: use WSL Ubuntu, then follow Linux steps")
    elif name == "totp":
        print("totp v1.1.2 release example:")
        if system == "darwin" and machine == "arm64":
            asset = "totp_1.1.2_darwin_arm64.tar.gz"
        elif system == "darwin":
            asset = "totp_1.1.2_darwin_amd64.tar.gz"
        elif machine in {"aarch64", "arm64"}:
            asset = "totp_1.1.2_linux_arm64.tar.gz"
        elif machine.startswith("arm"):
            asset = "totp_1.1.2_linux_arm.tar.gz"
        else:
            asset = "totp_1.1.2_linux_amd64.tar.gz"
        url = f"https://github.com/arcanericky/totp/releases/download/v1.1.2/{asset}"
        print(f"  wget {url}")
        print(f"  tar xf {asset}")
        print("  sudo chmod +x totp")
        print("  sudo mv totp /usr/local/bin/")
    elif name == "python dependency pexpect":
        print("Python venv setup:")
        print("  python3 -m venv .venv")
        print("  source .venv/bin/activate")
        print("  python -m pip install -r requirements.txt")
    elif name == "scripts/login_jump.exp":
        print(f"Script permission fix: chmod +x {LOGIN_SCRIPT}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Jumpserver automation prerequisites.")
    parser.add_argument("--host", default="Jumpserver", help="SSH config Host alias. Defaults to Jumpserver.")
    parser.add_argument("--totp-profile", default="jumpserver", help="totp profile name. Defaults to jumpserver.")
    parser.add_argument("--skip-totp-code", action="store_true", help="Do not execute totp profile during checks.")
    parser.add_argument("--hints", action="store_true", help="Print install hints for failed checks.")
    args = parser.parse_args()

    results = [
        command_check("ssh"),
        command_check("zsh"),
        command_check("expect"),
        command_check("totp"),
        command_check("python3"),
        check_login_script(),
        check_pexpect(),
        check_ssh_config(args.host),
    ]
    if not args.skip_totp_code:
        results.append(check_totp_code(args.totp_profile))

    for result in results:
        print(f"{result.level} {result.name}: {result.detail}")
        if args.hints and result.level == "FAIL":
            print_install_hint(result.name)

    return 1 if any(result.level == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
