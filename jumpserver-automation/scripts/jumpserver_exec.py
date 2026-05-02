#!/usr/bin/env python3
"""Log in through Jumpserver, select one asset, and execute an explicit command."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pexpect

from parse_assets import Asset, is_ip, markdown_table, match_assets, parse_assets


ROOT = Path(__file__).resolve().parents[1]
LOGIN_SCRIPT = ROOT / "scripts" / "login_jump.exp"
PROMPTS = [r"Opt>", r"\[Host\]>", r"[$#]\s*$"]


def run_preflight(host: str, totp_profile: str) -> None:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "preflight_check.py"),
        "--host",
        host,
        "--totp-profile",
        totp_profile,
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def spawn_entry(entry_command: str | None, host: str, totp_profile: str, timeout: int) -> pexpect.spawn:
    env = os.environ.copy()
    env["JUMPSERVER_SSH_HOST"] = host
    env["TOTP_PROFILE"] = totp_profile

    if entry_command:
        if entry_command == "jump":
            command = "/bin/zsh"
            args = ["-ic", "jump"]
        else:
            parts = shlex.split(entry_command)
            command = parts[0]
            args = parts[1:]
    else:
        command = str(LOGIN_SCRIPT)
        args = []

    child = pexpect.spawn(command, args=args, encoding="utf-8", timeout=timeout, env=env)
    child.logfile_read = sys.stdout
    return child


def expect_any(child: pexpect.spawn, timeout: int) -> int:
    return child.expect(PROMPTS, timeout=timeout)


def read_asset_page(child: pexpect.spawn, timeout: int) -> str:
    child.expect([r"\[Host\]>", r"Opt>", pexpect.TIMEOUT], timeout=timeout)
    return f"{child.before}{child.after if isinstance(child.after, str) else ''}"


def collect_asset_pages(child: pexpect.spawn, timeout: int, max_pages: int) -> list[Asset]:
    collected: list[Asset] = []
    seen_keys: set[tuple[str, str, str]] = set()

    child.sendline("r")
    expect_any(child, timeout)
    child.sendline("p")

    for page_number in range(1, max_pages + 1):
        page = read_asset_page(child, timeout)
        assets, footer = parse_assets(page)
        for asset in assets:
            key = (asset.id, asset.name, asset.address)
            if key not in seen_keys:
                seen_keys.add(key)
                collected.append(asset)

        current = footer.get("page")
        total = footer.get("total_pages")
        if not current or not total or current >= total:
            break

        print(f"INFO collecting next Jumpserver asset page: {current + 1}/{total}", file=sys.stderr)
        child.sendline("n")
    else:
        print(f"WARN stopped after --max-pages={max_pages}; results may be incomplete.", file=sys.stderr)

    return collected


def search_target(child: pexpect.spawn, target: str, timeout: int) -> tuple[str, list[Asset]]:
    child.sendline(target)
    child.expect([r"\[Host\]>", r"Opt>", r"[$#]\s*$", pexpect.TIMEOUT], timeout=timeout)
    output = f"{child.before}{child.after if isinstance(child.after, str) else ''}"
    if isinstance(child.after, str) and re.search(r"[$#]\s*$", child.after):
        return "logged_in", []
    assets, _ = parse_assets(output)
    return "candidates", assets


def run_remote_command(child: pexpect.spawn, command: str, timeout: int) -> int:
    marker = "__JUMPSERVER_EXEC_EXIT__"
    verify = "hostname; hostname -I 2>/dev/null || true; whoami; pwd"
    wrapped = f"{verify}; {command}; __rc=$?; printf '\\n{marker}%s\\n' \"$__rc\""
    child.sendline(wrapped)
    child.expect(rf"{marker}(\d+)", timeout=timeout)
    return int(child.match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute a command on a Jumpserver Linux asset selected by IP, name, remark, or ID."
    )
    parser.add_argument("--target", required=True, help="Target asset IP, name, remark, ID, or keyword.")
    parser.add_argument("--cmd", required=True, help="Explicit remote command to execute.")
    parser.add_argument("--host", default="Jumpserver", help="SSH config Host alias. Defaults to Jumpserver.")
    parser.add_argument("--totp-profile", default="jumpserver", help="totp profile name. Defaults to jumpserver.")
    parser.add_argument("--entry-command", help="Optional login command. Use 'jump' to force the shell alias.")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip prerequisite checks.")
    parser.add_argument("--timeout", type=int, default=30, help="pexpect timeout in seconds.")
    parser.add_argument("--max-pages", type=int, default=50, help="Maximum Jumpserver asset pages to collect. Defaults to 50.")
    parser.add_argument(
        "--search-first",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Type --target at the Jumpserver [Host]> prompt before falling back to paginated asset collection. Defaults to true.",
    )
    args = parser.parse_args()

    if re.search(r"\b(rm\s+-rf|reboot|shutdown|mkfs|dd\s+if=|systemctl\s+restart)\b", args.cmd):
        print("WARN command appears production-impacting; confirm risk, rollback, and NO_PROXY before execution.", file=sys.stderr)

    if not args.skip_preflight:
        run_preflight(args.host, args.totp_profile)

    child = spawn_entry(args.entry_command, args.host, args.totp_profile, args.timeout)
    try:
        expect_any(child, args.timeout)
        if args.search_first and not is_ip(args.target):
            status, candidates = search_target(child, args.target, args.timeout)
            if status == "logged_in":
                return run_remote_command(child, args.cmd, args.timeout)
            matches = match_assets(candidates, args.target)
            if len(matches) == 1:
                child.sendline(matches[0].id)
                child.expect([r"[$#]\s*$", pexpect.TIMEOUT], timeout=args.timeout)
                return run_remote_command(child, args.cmd, args.timeout)
            if len(matches) > 1:
                print("Jumpserver search matched multiple assets; refusing to choose silently.", file=sys.stderr)
                print(markdown_table(matches), file=sys.stderr)
                return 2

            print("INFO Jumpserver search did not uniquely match; falling back to paginated asset collection.", file=sys.stderr)

        assets = collect_asset_pages(child, args.timeout, args.max_pages)
        matches = match_assets(assets, args.target)

        if len(matches) != 1:
            if matches:
                print("Matched multiple assets; refusing to choose silently.", file=sys.stderr)
                print(markdown_table(matches), file=sys.stderr)
            else:
                print("No asset matched after collecting Jumpserver asset pages. Refine target or verify RBAC.", file=sys.stderr)
            return 2

        child.sendline(matches[0].id)
        child.expect([r"[$#]\s*$", pexpect.TIMEOUT], timeout=args.timeout)
        return run_remote_command(child, args.cmd, args.timeout)
    finally:
        try:
            child.sendline("exit")
            child.close(force=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
