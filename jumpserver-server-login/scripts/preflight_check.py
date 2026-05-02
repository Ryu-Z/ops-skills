#!/usr/bin/env python3
"""Validate prerequisites for the Jumpserver automation skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGIN_SCRIPT = ROOT / "scripts" / "login_jump.exp"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
SKILL_FILE = ROOT / "SKILL.md"


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


def skill_name() -> str:
    if SKILL_FILE.exists():
        for line in SKILL_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("name:"):
                return line.split(":", 1)[1].strip()
    return ROOT.name


def default_state_file(name: str) -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".codex" / "state"
    return root / name / "preflight.json"


def read_state(path: Path) -> dict[str, object] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return {"schema_version": 1, "ok": False, "note": "state file is not valid JSON"}


def write_state(path: Path, name: str, host: str, totp_profile: str, results: list["Result"]) -> None:
    failures = [result.name for result in results if result.level == "FAIL"]
    warnings = [result.name for result in results if result.level == "WARN"]
    state = {
        "schema_version": 1,
        "skill_name": name,
        "last_checked_at": datetime.now(UTC).isoformat(),
        "ok": not failures,
        "host_alias": host,
        "totp_profile": totp_profile,
        "failed_checks": failures,
        "warned_checks": warnings,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_state_summary(path: Path, state: dict[str, object] | None) -> None:
    if not state:
        print(f"STATE first run: no preflight state found at {path}")
        return
    status = "OK" if state.get("ok") else "FAIL"
    checked_at = state.get("last_checked_at", "unknown")
    failures = state.get("failed_checks") or []
    print(f"STATE previous preflight: {status} at {checked_at}")
    if failures:
        print(f"STATE previous failures: {', '.join(str(item) for item in failures)}")


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
    if VENV_PYTHON.exists():
        completed = run(
            [str(VENV_PYTHON), "-c", "import pexpect"],
            timeout=10,
        )
        if completed.returncode == 0:
            return Result(
                "FAIL",
                "python dependency pexpect",
                f"missing in current interpreter; rerun with {VENV_PYTHON} scripts/preflight_check.py",
            )
    return Result(
        "FAIL",
        "python dependency pexpect",
        "missing; ask permission, then run python3 scripts/init_wizard.py --apply",
    )


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
        print("Python dependency setup. Ask the user before running:")
        print("  python3 scripts/init_wizard.py --apply")
        print("Direct venv setup:")
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
    parser.add_argument("--no-state", action="store_true", help="Do not read or write the local preflight state file.")
    parser.add_argument("--show-state", action="store_true", help="Print previous local preflight state before running checks.")
    parser.add_argument("--state-file", help="Override the local preflight state file path.")
    args = parser.parse_args()
    name = skill_name()
    state_path = Path(args.state_file).expanduser() if args.state_file else default_state_file(name)

    if not args.no_state and args.show_state:
        print_state_summary(state_path, read_state(state_path))

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

    if not args.no_state:
        write_state(state_path, name, args.host, args.totp_profile, results)
        print(f"STATE wrote preflight result: {state_path}")

    return 1 if any(result.level == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
