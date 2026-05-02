---
name: jumpserver-server-login
description: Automate Jumpserver Linux asset login through ssh Jumpserver, totp jumpserver, and bundled Expect/Python scripts, then execute an explicit command on the selected server with production-risk checks. Use when the user asks to initialize Jumpserver access, validate Jumpserver prerequisites, select a Jumpserver asset, log in through Jumpserver, or run a command on a Linux server via Jumpserver.
---

# Jumpserver Server Login

## Scope

Use this skill to initialize and operate a Linux/macOS Jumpserver workflow:

1. Validate local prerequisites.
2. Use `totp jumpserver` and `ssh Jumpserver` through `scripts/login_jump.exp`.
3. Refresh and parse Jumpserver assets.
4. Select exactly one target asset.
5. Execute a user-provided explicit command with `scripts/jumpserver_exec.py --cmd`.

Windows is not the primary target. For Windows users, prefer WSL Ubuntu and follow the Linux steps.

## Response Shape

Reply in Chinese with:

1. 结论
2. 风险提示
3. 操作步骤
4. 验证命令
5. 回滚或清理方案

For any production change, deletion, restart, config replacement, or batch operation, warn before commands. Remind the user to check whether `NO_PROXY` includes intranet addresses, Kubernetes Service CIDRs, `.local`, `.internal`, `.svc`, `.cluster.local`, localhost, and VPC/private CIDRs.

## Initialization

Run the preflight first:

```bash
cd jumpserver-server-login
python3 scripts/preflight_check.py --show-state
```

The preflight keeps a local state file at `~/.codex/state/<skill-name>/preflight.json`. Use it only for safe metadata such as last check time, pass/fail status, failed check names, host alias, and totp profile. Do not store Hostname, IdentityFile, OTP, TOTP seed values, passwords, tokens, or asset details.

If a prerequisite is missing, ask about one item at a time. Do not ask for all fields at once.
If `preflight_check.py` reports `FAIL python dependency pexpect`, do not silently install packages. Ask the user for permission, then run the initializer with apply mode:

```bash
python3 scripts/init_wizard.py --apply
```

For an interactive dry-run or setup flow:

```bash
python3 scripts/init_wizard.py
python3 scripts/init_wizard.py --apply
```

### expect

macOS:

```bash
brew install expect
```

Ubuntu/Debian:

```bash
sudo apt-get update && sudo apt-get install -y expect
```

RHEL/CentOS/Rocky/Amazon Linux:

```bash
sudo dnf install -y expect
```

Windows: use WSL Ubuntu, then follow the Linux steps.

### totp

Install `totp` v1.1.2 from `https://github.com/arcanericky/totp/releases` according to `uname -s` and `uname -m`.

macOS arm64:

```bash
wget https://github.com/arcanericky/totp/releases/download/v1.1.2/totp_1.1.2_darwin_arm64.tar.gz
tar xf totp_1.1.2_darwin_arm64.tar.gz
sudo chmod +x totp
sudo mv totp /usr/local/bin/
totp version
```

macOS amd64:

```bash
wget https://github.com/arcanericky/totp/releases/download/v1.1.2/totp_1.1.2_darwin_amd64.tar.gz
tar xf totp_1.1.2_darwin_amd64.tar.gz
sudo chmod +x totp
sudo mv totp /usr/local/bin/
totp version
```

Linux amd64:

```bash
wget https://github.com/arcanericky/totp/releases/download/v1.1.2/totp_1.1.2_linux_amd64.tar.gz
tar xf totp_1.1.2_linux_amd64.tar.gz
sudo chmod +x totp
sudo mv totp /usr/local/bin/
totp version
```

Linux arm64:

```bash
wget https://github.com/arcanericky/totp/releases/download/v1.1.2/totp_1.1.2_linux_arm64.tar.gz
tar xf totp_1.1.2_linux_arm64.tar.gz
sudo chmod +x totp
sudo mv totp /usr/local/bin/
totp version
```

If Go source installation is preferred or release download is unavailable:

```bash
go install github.com/arcanericky/totp@latest
GOPROXY=https://goproxy.cn,direct go install github.com/arcanericky/totp@latest
```

Validate without printing the OTP:

```bash
totp jumpserver >/dev/null
```

Do not commit TOTP seed values or local config files.

### Python venv

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### SSH Config

If `ssh -G Jumpserver` fails or contains placeholders, ask one field at a time:

1. `Host`: default example `Jumpserver`.
2. `Hostname`: no default; ask for raw input only. Example text outside the input: `192.0.2.10 / jumpserver.example.com`.
3. `User`: default example `admin`.
4. `Port`: default example `2222`; the real value depends on the environment.
5. `IdentityFile`: default example `~/.ssh/id_rsa`.

Preview before writing:

```sshconfig
Host Jumpserver
    Hostname <hostname-from-user>
    User admin
    Port 2222
    IdentityFile ~/.ssh/id_rsa
```

Verify:

```bash
ssh -G Jumpserver | sed -n '1,40p'
ssh Jumpserver
```

## Login Entry

The default login entry is the bundled script:

```bash
chmod +x scripts/login_jump.exp
"$(pwd)/scripts/login_jump.exp"
```

The existing alias is optional:

```bash
alias jump="/absolute/path/to/jumpserver-server-login/scripts/login_jump.exp"
```

If the `jump` alias is unavailable in a non-interactive shell, use the bundled script absolute path.

## Execute Command

Run only an explicit command:

```bash
source .venv/bin/activate
python scripts/jumpserver_exec.py --target <ip-or-name-or-remark> --cmd 'hostname; whoami'
```

The script logs in, runs `r` and `p`, parses assets, requires exactly one match, enters the asset ID, verifies host identity, then runs `--cmd`.

## Matching Rules

Use `scripts/parse_assets.py` for Jumpserver `p` output. Supported headers include `ID`/`编号`, `名称`/`主机名`, `备注`, `地址`/`IP`, and `平台`/`系统`.

Matching order:

1. Exact IP address.
2. Exact name, remark, or ID.
3. Case-insensitive substring across ID, name, address, remark, and platform.

Do not silently choose from multiple matches.

## Risk And Rollback

- Wrong asset selection can affect production. Confirm IP, name, and business purpose before running commands.
- Restarts, deletes, config replacements, or batch commands are production changes and require explicit confirmation.
- Jumpserver visibility depends on RBAC and refresh timing.
- If the wrong host is selected, run `exit` immediately.
- If a command already ran on the wrong host, stop, capture command history, time window, user, host identity, and affected service, then use the service-specific rollback runbook.
