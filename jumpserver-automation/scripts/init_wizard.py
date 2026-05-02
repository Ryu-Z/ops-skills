#!/usr/bin/env python3
"""Interactive one-question-at-a-time initializer for Jumpserver automation."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGIN_SCRIPT = ROOT / "scripts" / "login_jump.exp"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


def run(command: str, apply: bool) -> None:
    print(f"$ {command}")
    if apply:
        subprocess.run(command, shell=True, check=True, cwd=ROOT)


def yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("请输入 y 或 n。")


def ask_value(prompt: str, default: str | None = None, required: bool = True) -> str:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        answer = input(f"{prompt}{suffix}: ").strip()
        if not answer and default is not None:
            answer = default
        if answer or not required:
            return answer
        print("该项不能为空。")


def install_expect_command() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "brew install expect"
    if Path("/etc/debian_version").exists():
        return "sudo apt-get update && sudo apt-get install -y expect"
    return "sudo dnf install -y expect"


def totp_asset() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin" and machine == "arm64":
        return "totp_1.1.2_darwin_arm64.tar.gz"
    if system == "darwin":
        return "totp_1.1.2_darwin_amd64.tar.gz"
    if system.startswith("windows"):
        return "totp_1.1.2_windows_amd64.zip"
    if machine in {"aarch64", "arm64"}:
        return "totp_1.1.2_linux_arm64.tar.gz"
    if machine.startswith("arm"):
        return "totp_1.1.2_linux_arm.tar.gz"
    return "totp_1.1.2_linux_amd64.tar.gz"


def install_totp_commands() -> list[str]:
    asset = totp_asset()
    url = f"https://github.com/arcanericky/totp/releases/download/v1.1.2/{asset}"
    if asset.endswith(".zip"):
        return [
            f"powershell.exe -Command \"Invoke-WebRequest -Uri {url} -OutFile totp.zip\"",
            "powershell.exe -Command \"Expand-Archive .\\totp.zip -DestinationPath .\\totp\"",
        ]
    return [
        f"wget {url}",
        f"tar xf {asset}",
        "sudo chmod +x totp",
        "sudo mv totp /usr/local/bin/",
    ]


def venv_has_pexpect() -> bool:
    if not VENV_PYTHON.exists():
        return False
    completed = subprocess.run(
        [str(VENV_PYTHON), "-c", "import pexpect"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.returncode == 0


def ssh_config_resolves(host: str) -> bool:
    config = Path.home() / ".ssh" / "config"
    if not config.exists():
        return False
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
            in_host = host in value.split()
            continue
        if in_host and key in {"hostname", "user", "port", "identityfile"} and key not in block:
            block[key] = value
    required = {"hostname", "user", "port", "identityfile"}
    if set(block) & required != required:
        return False
    if any("<" in value or ">" in value or value.endswith(".example.com") for value in block.values()):
        return False

    completed = subprocess.run(
        ["ssh", "-G", host],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        return False
    required = {"hostname", "user", "port", "identityfile"}
    found = set()
    for line in completed.stdout.splitlines():
        if " " not in line:
            continue
        key, value = line.split(None, 1)
        if key in required and value.strip() and "<" not in value and ">" not in value:
            found.add(key)
    return required <= found


def valid_hostname(value: str) -> bool:
    if not value or re.search(r"\s|/|://", value):
        return False
    return True


def configure_ssh(apply: bool) -> None:
    host = ask_value("请输入 SSH Host 别名", default="Jumpserver")
    while True:
        print("请输入 Jumpserver Hostname（连接地址，无默认值）。示例：192.0.2.10 / jumpserver.example.com")
        hostname = ask_value("Hostname", default=None)
        if valid_hostname(hostname):
            break
        print("Hostname 不应包含协议、斜杠、空格或端口；端口会在下一步单独询问。")
    user = ask_value("请输入 Jumpserver SSH User", default="admin")
    port = ask_value("请输入 Jumpserver SSH Port", default="2222")
    identity = ask_value("请输入 Jumpserver IdentityFile 路径", default="~/.ssh/id_rsa")

    block = "\n".join(
        [
            f"Host {host}",
            f"    Hostname {hostname}",
            f"    User {user}",
            f"    Port {port}",
            f"    IdentityFile {identity}",
            "",
        ]
    )
    print("\n将生成以下 SSH config：")
    print(block)
    if yes_no("是否追加到 ~/.ssh/config？", default=False):
        command = (
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f"printf '%s\\n' {shlex_quote(block)} >> ~/.ssh/config && chmod 600 ~/.ssh/config"
        )
        run(command, apply)
        if not apply:
            print("当前为 dry-run；加入 --apply 才会写入。")


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize Jumpserver automation one prompt at a time.")
    parser.add_argument("--apply", action="store_true", help="Execute selected setup commands. Default is dry-run.")
    parser.add_argument("--host", default="Jumpserver", help="SSH config Host alias to check.")
    args = parser.parse_args()

    if not args.apply:
        print("dry-run 模式：只展示将执行的命令，不修改系统。加入 --apply 才会执行。")

    if not shutil.which("expect") and yes_no("检测到 expect 未安装，是否安装？"):
        run(install_expect_command(), args.apply)

    if not shutil.which("totp") and yes_no("检测到 totp 未安装，是否安装 v1.1.2？"):
        for command in install_totp_commands():
            run(command, args.apply)

    if not venv_has_pexpect() and yes_no("检测到 Python venv/pexpect 未就绪，是否创建或修复 .venv 并安装 requirements.txt？"):
        run("python3 -m venv .venv", args.apply)
        run(". .venv/bin/activate && python -m pip install -r requirements.txt", args.apply)

    if LOGIN_SCRIPT.exists() and not LOGIN_SCRIPT.stat().st_mode & stat.S_IXUSR:
        if yes_no("检测到 scripts/login_jump.exp 不可执行，是否 chmod +x？"):
            run(f"chmod +x {shlex_quote(str(LOGIN_SCRIPT))}", args.apply)

    if not ssh_config_resolves(args.host):
        if yes_no(f"检测到 ssh config Host {args.host} 未就绪，是否逐项配置？"):
            configure_ssh(args.apply)

    print("初始化向导完成。建议继续运行：python3 scripts/preflight_check.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
