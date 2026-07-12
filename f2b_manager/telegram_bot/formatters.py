"""
f2b_manager.telegram_bot.formatters
====================================

消息格式化工具（HTML 格式）。

所有输出到 Telegram 的文本都经过 HTML 转义，避免注入。
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage.models import (
        BanEvent, DailyStat, Fail2banStatus, InstallResult,
        JailInfo, JailStatus,
    )


# ──────────────────────────────────────────────
# 基础工具
# ──────────────────────────────────────────────

def esc(text) -> str:
    """HTML 转义（None 安全）"""
    if text is None:
        return ""
    return html.escape(str(text), quote=False)


def _state_emoji(state: str) -> str:
    """服务状态 emoji"""
    if state == "running":
        return "\U0001f7e2"  # 🟢
    if state == "stopped":
        return "\U0001f534"  # 🔴
    return "\u26a0\ufe0f"  # ⚠️


# ──────────────────────────────────────────────
# 状态格式化
# ──────────────────────────────────────────────

def format_status(status: "Fail2banStatus") -> str:
    """格式化 fail2ban 整体状态"""
    state = status.state.value if hasattr(status.state, "value") else str(status.state)
    emoji = _state_emoji(state)

    lines = [
        f"\U0001f4cb <b>Fail2ban 状态总览</b>",
        "",
        f"{emoji} <b>服务状态:</b> {esc(state)}",
        f"\u23f1 <b>运行时长:</b> {esc(status.uptime) or '未知'}",
        f"\U0001f4e6 <b>版本:</b> <code>{esc(status.version) or '未知'}</code>",
        f"\U0001f510 <b>Jail 数量:</b> <code>{status.jail_count}</code>",
        f"\U0001f6ab <b>总封禁数:</b> <code>{status.total_bans}</code>",
    ]
    return "\n".join(lines)


def format_jails(jails: list["JailInfo"]) -> str:
    """格式化 jail 列表"""
    if not jails:
        return "\U0001f511 <b>Jail 列表</b>\n\n暂无启用的 jail。"

    lines = ["\U0001f511 <b>Jail 列表</b>", ""]

    for jail in jails:
        status_icon = "\u2705" if jail.enabled else "\u274c"
        lines.append(
            f"{status_icon} <code>{esc(jail.name)}</code>"
            f"  |  当前封禁: <b>{jail.current_ban}</b>"
            f"  |  累计失败: <b>{jail.total_failed}</b>"
        )

    return "\n".join(lines)


def format_jail_detail(jail: "JailStatus") -> str:
    """格式化单个 jail 详情"""
    lines = [
        f"\U0001f50d <b>Jail 详情: {esc(jail.name)}</b>",
        "",
        f"\u2705 <b>启用:</b> {'是' if jail.enabled else '否'}",
        f"\U0001f6ab <b>当前封禁 IP:</b> <code>{jail.current_ban}</code>",
        f"\U0001f4ca <b>累计失败:</b> <code>{jail.total_failed}</code>",
        f"\U0001f4c8 <b>累计封禁:</b> <code>{jail.total_banned}</code>",
        f"\u23f1 <b>检测窗口:</b> <code>{esc(jail.findtime)}</code>",
        f"\u23f1 <b>封禁时长:</b> <code>{esc(jail.bantime)}</code>",
        f"\U0001f501 <b>最大重试:</b> <code>{jail.maxretry}</code>",
    ]

    if jail.banned_ips:
        lines.append("")
        lines.append("\U0001f4cd <b>当前被封禁 IP:</b>")
        for ip in jail.banned_ips:
            lines.append(f"  • <code>{esc(ip)}</code>")
    else:
        lines.append("")
        lines.append("\U0001f4cd 当前无被封禁 IP")

    return "\n".join(lines)


def format_banned_ips(ips: list[str], countries: dict[str, str] | None = None) -> str:
    """格式化被封禁 IP 列表

    Args:
        ips: IP 列表
        countries: IP→国家字典，如 {"1.2.3.4": "美国 🇺🇸"}
    """
    if not ips:
        return "\U0001f6ab <b>当前封禁 IP 列表</b>\n\n当前没有被封禁的 IP。\n服务器一切平安 \U0001f60a"

    lines = [
        f"\U0001f6ab <b>当前封禁 IP 列表</b>",
        f"共 <b>{len(ips)}</b> 个 IP 被封禁",
        "",
    ]

    for i, ip in enumerate(ips, 1):
        country = (countries or {}).get(ip, "")
        if country:
            lines.append(f"  {i}. <code>{esc(ip)}</code>  {country}")
        else:
            lines.append(f"  {i}. <code>{esc(ip)}</code>")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# 操作结果格式化
# ──────────────────────────────────────────────

def format_install_result(
    result: "InstallResult", action: str = "安装"
) -> str:
    """格式化安装/卸载/更新结果"""
    icon = "\u2705" if result.success else "\u274c"
    lines = [
        f"{icon} <b>Fail2ban {action}{'完成' if result.success else '失败'}</b>",
        "",
        f"\U0001f4e4 <b>消息:</b> {esc(result.message)}",
    ]

    if result.version:
        lines.append(f"\U0001f4e6 <b>版本:</b> <code>{esc(result.version)}</code>")
    if result.old_version:
        lines.append(
            f"\U0001f4e4 <b>旧版本:</b> <code>{esc(result.old_version)}</code>"
        )
    if result.elapsed_seconds > 0:
        lines.append(
            f"\u23f1 <b>耗时:</b> <code>{result.elapsed_seconds:.1f}s</code>"
        )

    if result.details:
        lines.append("")
        lines.append("\U0001f4dd <b>详情:</b>")
        for detail in result.details:
            lines.append(f"  • {esc(detail)}")

    return "\n".join(lines)


def format_ban_result(ip: str, jail: str, success: bool, action: str = "封禁") -> str:
    """格式化封禁/解封结果"""
    icon = "\u2705" if success else "\u274c"
    return (
        f"{icon} <b>{action}{'成功' if success else '失败'}</b>\n\n"
        f"\U0001f4cd IP: <code>{esc(ip)}</code>\n"
        f"\U0001f3f7 Jail: <code>{esc(jail)}</code>"
    )


# ──────────────────────────────────────────────
# 统计与报告格式化
# ──────────────────────────────────────────────

def format_ban_event(event: "BanEvent") -> str:
    """格式化封禁事件"""
    action_icon = "\U0001f6a8" if event.action.value == "ban" else "\u2705"
    country_str = f"{esc(event.country)}" if event.country else "未知"

    lines = [
        f"{action_icon} <b>封禁事件</b>",
        "",
        f"\U0001f4cd IP: <code>{esc(event.ip)}</code>",
        f"\U0001f3f7 Jail: <code>{esc(event.jail)}</code>",
        f"\U0001f50d 动作: <b>{esc(event.action.value)}</b>",
        f"\U0001f30d 归属: {country_str}",
        f"\U0001f522 失败次数: <b>{event.failures}</b>",
        f"\U0001f552 时间: {esc(event.timestamp.strftime('%Y-%m-%d %H:%M:%S'))}",
    ]

    if event.matches:
        preview = event.matches[:200]
        lines.append(f"\U0001f4dd 匹配日志:\n<pre>{esc(preview)}</pre>")

    return "\n".join(lines)


def format_daily_stats(stats: list["DailyStat"]) -> str:
    """格式化每日统计"""
    if not stats:
        return "\U0001f4ca <b>每日统计</b>\n\n暂无统计数据。"

    lines = ["\U0001f4ca <b>每日封禁统计</b>", ""]

    for stat in stats:
        country = esc(stat.top_country) if stat.top_country else "-"
        lines.append(
            f"<b>{esc(stat.date)}</b>"
            f"  |  封禁: <code>{stat.total_bans}</code>"
            f"  |  独立 IP: <code>{stat.unique_ips}</code>"
            f"  |  Top: {country}"
        )

    return "\n".join(lines)


def format_stats_summary(
    total_bans: int,
    unique_ips: int,
    top_ips: list[tuple[str, int]],
    top_countries: list[tuple[str, int]],
    days: int = 7,
) -> str:
    """格式化统计摘要"""
    lines = [
        f"\U0001f4ca <b>最近 {days} 天封禁统计</b>",
        "",
        f"\U0001f6ab <b>总封禁次数:</b> <code>{total_bans}</code>",
        f"\U0001f310 <b>独立 IP 数:</b> <code>{unique_ips}</code>",
    ]

    if top_ips:
        lines.append("")
        lines.append("\U0001f525 <b>Top 攻击 IP:</b>")
        for i, (ip, count) in enumerate(top_ips, 1):
            lines.append(f"  {i}. <code>{esc(ip)}</code> — <b>{count}</b> 次")

    if top_countries:
        lines.append("")
        lines.append("\U0001f30d <b>Top 攻击来源国家:</b>")
        for i, (country, count) in enumerate(top_countries, 1):
            lines.append(f"  {i}. {esc(country)} — <b>{count}</b> 次")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# 系统消息格式化
# ──────────────────────────────────────────────

def format_welcome(chat_id: int, level_name: str = "访客") -> str:
    """欢迎消息 + chat_id"""
    return (
        "\U0001f44b <b>欢迎使用 f2b-manager Bot</b>\n\n"
        "VPS Fail2ban 管理系统，通过 Telegram 远程管理 fail2ban。\n\n"
        f"\U0001f194 <b>你的 Chat ID:</b> <code>{chat_id}</code>\n"
        f"\U0001f511 <b>权限等级:</b> {esc(level_name)}\n\n"
        "将上面的 Chat ID 填入配置文件的 "
        "<code>admin_chat_ids</code> 或 <code>operator_chat_ids</code> 中。\n\n"
        "输入 /help 查看所有可用命令。"
    )


def format_help(level_name: str = "访客") -> str:
    """命令帮助"""
    lines = [
        "\U0001f4da <b>命令帮助</b>",
        f"\U0001f511 你的权限: <b>{esc(level_name)}</b>",
        "",
        "<b>📋 基础命令</b>",
        "/start — 欢迎信息 + 显示 Chat ID",
        "/help — 显示此帮助",
        "/cancel — 取消当前操作",
        "",
        "<b>🔍 状态查询（操作员+）</b>",
        "/status — Fail2ban 运行状态总览",
        "/jails — 列出所有 Jail",
        "/banned — 列出当前被封禁 IP",
        "/jail &lt;name&gt; — 查看指定 Jail 详情（如 /jail sshd）",
        "/report — 生成即时报告",
        "/stats [天数] — 统计 N 天封禁情况（默认 7 天）",
        "/setnotify on|off — 开关实时预警",
        "",
        "<b>🔧 管理操作（管理员）</b>",
        "/ban &lt;ip&gt; — 手动封禁 IP（如 /ban 1.2.3.4）",
        "/unban &lt;ip&gt; — 解封 IP",
        "/install — 安装 Fail2ban",
        "/uninstall — 卸载 Fail2ban（需二次确认）",
        "/update — 更新 Fail2ban",
        "/reload — 重载 Fail2ban 配置",
        "/whitelist — 查看/管理白名单",
        "/setschedule — 设置定时报告频率",
    ]
    return "\n".join(lines)


def format_error(message: str) -> str:
    """错误消息"""
    return f"\u274c <b>错误</b>\n\n{esc(message)}"


def format_success(message: str) -> str:
    """成功消息"""
    return f"\u2705 <b>成功</b>\n\n{esc(message)}"


def format_progress(message: str) -> str:
    """进度消息"""
    return f"\u23f3 {esc(message)}"


def format_cancelled() -> str:
    """操作已取消"""
    return "\u274c 操作已取消。"


def format_not_ready() -> str:
    """功能尚未就绪"""
    return (
        "\u26a0\ufe0f <b>功能尚未就绪</b>\n\n"
        "Fail2ban 管理模块 (M1) 尚未加载。\n"
        "请在服务器上安装并运行 f2b-manager 后重试。"
    )
