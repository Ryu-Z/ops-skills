# ops-skills

Codex 运维技能集合。每个技能位于仓库根目录下的独立文件夹中，包含自己的 `SKILL.md`、脚本和运行依赖。

## Skills

| 技能 | 用途 | 主要环境 |
| --- | --- | --- |
| `jumpserver-automation` | 初始化 Jumpserver 自动登录环境，通过 `ssh Jumpserver` + `totp jumpserver` 登录 Jumpserver，选择 Linux 资产，并执行显式远端命令 | Linux/macOS，Windows 建议 WSL |

## jumpserver-automation

### 能力边界

- 默认先运行本地 preflight，不登录 Jumpserver，不进入任何服务器，不执行远端命令。
- 支持检查 `ssh`、`zsh`、`expect`、`totp`、Python 依赖、`scripts/login_jump.exp`、`~/.ssh/config` 中的 `Host Jumpserver`。
- 支持用 `scripts/init_wizard.py` 逐项初始化缺失依赖。
- 支持用 `scripts/jumpserver_exec.py --target ... --cmd ...` 先通过 Jumpserver 关键字搜索目标，必要时再收集资产分页，在唯一匹配的 Linux 资产上执行显式命令。
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

如果目标机上的命令依赖交互式 shell、alias、函数或需要先切换用户，可以这样说：

```text
使用 $jumpserver-automation 登录目标 <目标IP或名称>，进入交互式 shell，先执行 <alias-or-switch-user>，确认当前用户后再执行 <command>
```

示例：

```text
使用 $jumpserver-automation 登录目标 example-app，进入交互式 shell，先执行 appuser alias，确认 whoami 后再执行 kubectl get nodes
```

这类请求会让技能避免把 alias 当作普通非交互命令直接执行，优先在目标机的交互 shell 里发送命令并确认提示符变化。

目标匹配策略：

- 默认先输入 `--target` 到 Jumpserver `[Host]>` 搜索；名称、完整 IP、IP 前缀、名称本身是 IP 的资产都走这个路径。
- 示例：`example-app`、`192.0.2.10`、`192.0.2` 都可以作为搜索输入。
- 如果 Jumpserver 直接进入唯一资产，脚本会继续做主机确认并执行显式命令。
- 如果 Jumpserver 返回候选表，脚本会解析候选并只在唯一命中时继续。
- 如果搜索没有唯一结果，脚本会执行 `r`、`p` 收集资产列表后在本地匹配 `--target`。
- 如果页脚显示还有下一页，会自动输入 `n` 继续收集，默认最多 `50` 页；可用 `--max-pages` 调整。
- 只有唯一命中时才输入资产 `ID` 登录。
- 如果命中多个资产，会输出候选表并停止；例如输入 `192.0.2` 这类 IP 前缀通常会匹配多台机器，需要改用精确 IP、精确 ID 或更具体的名称/备注。

涉及删除、重启、替换配置、批量操作等生产变更时，应先确认目标主机、影响范围、操作窗口和回滚方案。同时检查 `NO_PROXY` 是否包含内网地址、Kubernetes Service 网段、`.local`、`.internal`、`.svc`、`.cluster.local`、localhost 和 VPC/private CIDR，避免代理链路影响内网访问。
