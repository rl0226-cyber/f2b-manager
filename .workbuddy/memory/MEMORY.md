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
