#!/bin/bash
# ───────────────────────────────────────────────────────────
# f2b-notify.sh - Fail2ban → f2b-manager 通知桥接脚本
# ───────────────────────────────────────────────────────────
# 被 fail2ban action 调用，将封禁/解封/启停事件转发给
# f2b-manager CLI 的 notify 子命令。CLI 内部构造消息后通过
# Telegram Bot 发送预警。
#
# 部署路径: /usr/local/bin/f2b-notify.sh
# 权限:     755 (root:root)
#
# 设计原则:
#   - 永远 exit 0，避免影响 fail2ban 正常工作
#   - 后台异步执行，不阻塞 fail2ban action 链
#   - 所有输出重定向到 /dev/null（避免污染 fail2ban 日志）
#
# 参数说明:
#   $1 - 事件类型: ban / unban / start / stop
#   $2 - 内容（事件类型不同含义不同）:
#         ban:   IP 地址
#         unban: IP 地址
#         start: jail 名称
#         stop:  jail 名称
#   $3 - jail 名称（ban/unban 时有效）
#   $4 - 失败次数（仅 ban 时有效）
#   $5 - 匹配日志行（仅 ban 时有效，可能为空）
# ───────────────────────────────────────────────────────────

set -e

# ── 参数 ──────────────────────────────────
EVENT="${1:-}"
IP="${2:-}"
JAIL="${3:-}"
FAILURES="${4:-0}"
MATCHES="${5:-}"

# ── 参数校验 ──────────────────────────────
if [ -z "$EVENT" ]; then
    # 无参数调用，静默退出
    exit 0
fi

# ── CLI 路径（优先查找） ──────────────────
F2B_MANAGER=""
if command -v f2b-manager >/dev/null 2>&1; then
    F2B_MANAGER="f2b-manager"
elif [ -x /usr/local/bin/f2b-manager ]; then
    F2B_MANAGER="/usr/local/bin/f2b-manager"
elif [ -x /opt/f2b-manager/venv/bin/python ]; then
    # 开发/部署环境回退
    F2B_MANAGER="/opt/f2b-manager/venv/bin/python -m f2b_manager"
else
    # f2b-manager 未安装，记录到 syslog 后静默退出
    logger -t f2b-notify "f2b-manager CLI 未找到，跳过通知"
    exit 0
fi

# ── 转发事件（后台异步） ──────────────────
# 使用 nohup + 后台执行，确保不阻塞 fail2ban
# 超时 30 秒，防止网络问题导致僵尸进程堆积
nohup timeout 30 $F2B_MANAGER notify \
    --event "$EVENT" \
    --ip "$IP" \
    --jail "$JAIL" \
    --failures "$FAILURES" \
    --matches "$MATCHES" \
    >/dev/null 2>&1 &

# 永远返回 0
exit 0
