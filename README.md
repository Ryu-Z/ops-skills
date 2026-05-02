# ops-skills

公开、脱敏、可复用的 Codex 运维技能仓库。

这是一个多技能仓库。每个技能位于仓库根目录下的独立文件夹中，包含自己的 `SKILL.md`、脚本和运行依赖。仓库内容必须保持可公开发布，不应包含真实 Jumpserver 域名、内网资产地址、私钥材料、MFA 种子值、OTP、凭据或个人绝对路径。

## Skills

| 技能 | 原名称 | 用途 | 主要环境 |
| --- | --- | --- | --- |
| `jumpserver-automation` | `jumpserver-server-login` | 初始化 Jumpserver 自动登录环境，通过 `ssh Jumpserver` + `totp jumpserver` 登录 Jumpserver，选择 Linux 资产，并执行显式远端命令 | Linux/macOS，Windows 建议 WSL |

`jumpserver-server-login` 这个名字容易让 `jumpserver` 和 `server` 语义重复；仓库中已更名为 `jumpserver-automation`，更强调“Jumpserver 自动化登录与命令执行”的能力。

## jumpserver-automation

### 能力边界

- 默认先运行本地 preflight，不登录 Jumpserver，不进入任何服务器，不执行远端命令。
- 支持检查 `ssh`、`zsh`、`expect`、`totp`、Python 依赖、`scripts/login_jump.exp`、`~/.ssh/config` 中的 `Host Jumpserver`。
- 支持用 `scripts/init_wizard.py` 逐项初始化缺失依赖。
- 支持用 `scripts/jumpserver_exec.py --target ... --cmd ...` 在唯一匹配的 Linux 资产上执行显式命令。
- 不缓存密码、不保存 OTP、不提交 TOTP 种子值，不绕过 Jumpserver 审计。

### 安装到本地 Codex 技能目录

保留旧技能时，建议安装为新名字：

```bash
rsync -av --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  ./jumpserver-automation/ \
  ~/.codex/skills/jumpserver-automation/
```

### 初始化 Python 依赖

```bash
cd ~/.codex/skills/jumpserver-automation
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 首次验证

```bash
cd ~/.codex/skills/jumpserver-automation
source .venv/bin/activate
python scripts/preflight_check.py --show-state
```

preflight 会维护一个本地状态文件：

```text
~/.codex/state/jumpserver-automation/preflight.json
```

状态文件只保存安全元数据，例如上次检查时间、是否通过、失败项、`Host` 别名和 `totp` profile，不保存 Hostname、IdentityFile、OTP、TOTP 种子值、密码、token 或资产详情。

### 交互式初始化

如果 preflight 提示缺少依赖，先征得用户确认，再运行：

```bash
cd ~/.codex/skills/jumpserver-automation
python scripts/init_wizard.py --apply
```

初始化向导会逐项询问，例如是否安装 `expect`、是否安装 `totp`、是否创建 `.venv`、是否生成 `Host Jumpserver` 配置，不会一次性要求填写所有字段。

### Codex 调用示例

```text
使用 $jumpserver-automation 检查 Jumpserver 自动化环境
```

执行远端命令时必须显式给出目标和命令：

```text
使用 $jumpserver-automation 登录目标 <目标IP或名称>，执行 hostname; whoami
```

涉及删除、重启、替换配置、批量操作等生产变更时，应先确认目标主机、影响范围、操作窗口和回滚方案。同时检查 `NO_PROXY` 是否包含内网地址、Kubernetes Service 网段、`.local`、`.internal`、`.svc`、`.cluster.local`、localhost 和 VPC/private CIDR，避免代理链路影响内网访问。
