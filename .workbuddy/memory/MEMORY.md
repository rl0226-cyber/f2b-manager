# f2b-manager 项目长期记忆

## 项目概述
VPS Fail2ban 管理系统，集成 fail2ban 安装/卸载/更新 + Telegram 机器人定时报告 + 实时预警。

## 技术栈决策
- Python 3.10+ / python-telegram-bot (v21+) / APScheduler / SQLite / systemd
- 守护进程模式 (非 cron)，systemd 管理生命周期

## 核心架构
单守护进程内 4 模块: Fail2ban管理 / TelegramBot / Scheduler / Notifier
配置: /etc/f2b-manager/config.yaml (权限 600)
状态库: /var/lib/f2b-manager/state.db (SQLite)

## 关键设计
- 实时预警: Hook (fail2ban action telegram-notify.conf → notify.sh → CLI) + 轮询兜底 (5分钟对比SQLite)
- 鉴权: chat_id 三级权限 (admin/operator/viewer)
- 安全: 限流去重、危险操作二次确认、配置脱敏

## 项目目录
/Users/lilaifu/Desktop/workbuddy/Fail2ban脚本/
- 设计方案.md — 完整设计文档

## 状态
2026-07-10: 完成方案设计，待用户确认后进入编码阶段。
2026-07-11: 全部模块 M1-M6 编码完成。M6 测试 152 用例全部通过。
- M1: fail2ban 管理（parser / manager / installer / config_builder）
- M2: Telegram Bot 模块（10 个文件）
- M3: 实时预警模块（geoip / dedup / sender / notify.sh）
- M4: 定时任务与监控（reporter / health / scheduler）
- M5: 部署运维（install.sh / uninstall.sh / systemd / geoip-update.sh / docs）
- M6: 测试模块（7 个文件，152 用例）


## M2 Telegram Bot 模块详情
### 已创建文件
- `telegram_bot/auth.py` — AuthManager 三级权限 + require_admin/require_operator 装饰器
- `telegram_bot/deps.py` — BotDeps 共享依赖容器（避免循环导入）
- `telegram_bot/formatters.py` — HTML 格式化工具（状态/jail/封禁/报告/错误）
- `telegram_bot/keyboards.py` — 内联键盘（二次确认）
- `telegram_bot/handlers/status.py` — /status /jails /banned /jail
- `telegram_bot/handlers/manage.py` — /install /uninstall(ConversationHandler) /update /reload
- `telegram_bot/handlers/ban.py` — /ban /unban（含 IP 校验）
- `telegram_bot/handlers/report.py` — /report /stats
- `telegram_bot/handlers/config.py` — /whitelist /setnotify /setschedule
- `telegram_bot/bot.py` — F2BTelegramBot 主类（IMessageSender 协议实现）

### 关键设计决策
- 依赖注入: BotDeps 存入 Application.bot_data["deps"]，handler 通过 get_deps() 获取
- 装饰器: require_admin/require_operator 用 functools.wraps，未授权返回 None（不进入对话状态）
- 长耗时操作: _run_with_progress() 用 run_in_executor + asyncio.wait_for 轮询进度
- /uninstall: ConversationHandler 状态机 (CONFIRM=1)，per_message=False（入口是 CommandHandler）
- 鸭子类型 installer: deps.get_installer() 优先用显式 installer，回退检查 f2b_manager 是否有 install 方法
- venv 安装了 python-telegram-bot v22.8
- app.py 已更新: 传递 installer=self._f2b_installer 给 F2BTelegramBot
