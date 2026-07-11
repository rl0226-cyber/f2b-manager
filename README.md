# f2b-manager

VPS Fail2ban 管理系统 — 集成 Telegram 机器人定时报告与实时预警。

## 功能

- **Fail2ban 管理** — 安装 / 卸载 / 更新，自动适配 Debian/Ubuntu/CentOS/Rocky 等发行版
- **Telegram 机器人** — 18 条交互命令，远程查看状态、封禁 IP、管理服务
- **实时预警** — IP 被封禁时秒级推送到 Telegram，含归属地、失败次数、匹配日志
- **定时报告** — 每日 / 每周自动汇总封禁情况，Top 攻击来源排行
- **轮询兜底** — 每 5 分钟对比状态，补发遗漏的预警，保证不丢通知
- **健康检查** — 自动检测 fail2ban 服务状态，异常时自动重启并告警
- **交互式菜单** — 输入 `f2b` 即可打开管理菜单，引导式配置，新手友好

## 一键安装

### Root 用户（大多数 VPS 默认是 root）

```bash
curl -fsSL https://raw.githubusercontent.com/rl0226-cyber/f2b-manager/main/install.sh | bash
```

### 非 Root 用户（需要 sudo 权限）

```bash
curl -fsSL https://raw.githubusercontent.com/rl0226-cyber/f2b-manager/main/install.sh | sudo bash
```

### 备选方案（如果上面命令因缓存失败）

```bash
git clone https://github.com/rl0226-cyber/f2b-manager.git /tmp/f2b-manager && bash /tmp/f2b-manager/install.sh
```

脚本会自动检测并安装缺少的系统依赖（python3-venv、python3-pip、git 等），无需手动处理。

安装完成后会自动弹出交互式菜单，引导你：
1. 安装 Fail2ban
2. 配置 Telegram Bot（输入 Token 和 User ID，自动测试连接）
3. 启动服务

之后随时输入 `f2b` 即可再次打开管理菜单。

## 前置要求

- Linux VPS（推荐 Ubuntu 22.04 / Debian 12）
- Python 3.10+（脚本会自动检测，缺失时提示安装命令）
- root 权限
- 一个 Telegram 账号（用于创建 Bot）

## 创建 Telegram Bot

1. 打开 Telegram，搜索 `@BotFather`
2. 发送 `/newbot`，按提示输入名称
3. 复制返回的 **Bot Token**
4. 搜索 `@userinfobot`，给它发消息，获取你的 **User ID**

安装向导会引导你填入这两个值。

## 使用

安装完成后，在 Telegram 给你的 Bot 发命令：

| 命令 | 功能 |
|------|------|
| `/status` | 查看 fail2ban 运行状态 |
| `/banned` | 查看当前封禁 IP 列表 |
| `/ban 1.2.3.4` | 手动封禁 IP |
| `/unban 1.2.3.4` | 解封 IP |
| `/report` | 立即生成报告 |
| `/stats 7` | 查看 7 天统计 |
| `/help` | 查看所有命令 |

## 架构

```
VPS
├── f2b-manager (守护进程, systemd 管理)
│   ├── Fail2ban 管理模块
│   ├── Telegram Bot (18 命令, 三级鉴权)
│   ├── 实时预警 (action hook + 轮询兜底)
│   └── 定时任务 (APScheduler)
├── Fail2ban (系统服务)
│   └── telegram-notify action → notify.sh → f2b-manager
└── SQLite 状态库
```

## 技术栈

Python 3.10+ / python-telegram-bot / APScheduler / SQLite / systemd

## License

MIT
