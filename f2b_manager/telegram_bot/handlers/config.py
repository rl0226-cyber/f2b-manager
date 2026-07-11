"""
f2b_manager.telegram_bot.handlers.config
==========================================

配置管理命令 handler。

命令:
    /whitelist [add|remove <ip>]  — 查看/管理白名单
    /setnotify on|off              — 开关实时预警
    /setschedule <type> <args>     — 设置定时报告频率

权限:
    /whitelist     — 管理员 (ADMIN)
    /setnotify     — 操作员 (OPERATOR) 及以上
    /setschedule   — 管理员 (ADMIN)
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..auth import require_admin, require_operator
from ..deps import get_deps
from ..formatters import esc, format_error, format_success

logger = logging.getLogger(__name__)

# 配置覆盖键名
KEY_WHITELIST = "whitelist_ips"
KEY_NOTIFY_ENABLED = "notify_enabled"
KEY_SCHEDULE_DAILY_TIME = "schedule_daily_time"
KEY_SCHEDULE_DAILY_ENABLED = "schedule_daily_enabled"
KEY_SCHEDULE_WEEKLY_TIME = "schedule_weekly_time"
KEY_SCHEDULE_WEEKLY_DAY = "schedule_weekly_day"
KEY_SCHEDULE_WEEKLY_ENABLED = "schedule_weekly_enabled"

VALID_DAYS = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


# ──────────────────────────────────────────────
# /whitelist
# ──────────────────────────────────────────────

@require_admin
async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/whitelist [add|remove <ip>] — 查看/管理白名单"""
    deps = get_deps(context)

    # 无参数：显示当前白名单
    if not context.args:
        _show_whitelist(update, deps)
        return

    sub = context.args[0].lower()

    if sub in ("add", "remove", "del", "delete") and len(context.args) < 2:
        await update.message.reply_text(
            format_error("用法: /whitelist add|remove <ip>"), parse_mode="HTML"
        )
        return

    if sub in ("add",):
        await _whitelist_add(update, context, deps)
    elif sub in ("remove", "del", "delete"):
        await _whitelist_remove(update, context, deps)
    else:
        await update.message.reply_text(
            format_error(
                "用法:\n"
                "  /whitelist              — 查看白名单\n"
                "  /whitelist add <ip>     — 添加白名单\n"
                "  /whitelist remove <ip>  — 移除白名单"
            ),
            parse_mode="HTML",
        )


def _get_whitelist(deps) -> list[str]:
    """从 db 读取白名单（config_overrides）"""
    if deps.db is None:
        return list(deps.config.fail2ban.ignoreip)
    raw = deps.db.get_config_override(KEY_WHITELIST, "")
    if raw:
        return [ip.strip() for ip in raw.split(",") if ip.strip()]
    return list(deps.config.fail2ban.ignoreip)


def _set_whitelist(deps, ips: list[str]) -> None:
    """保存白名单到 db"""
    if deps.db is None:
        return
    deps.db.set_config_override(KEY_WHITELIST, ",".join(ips))


async def _show_whitelist(update, deps) -> None:
    """显示当前白名单"""
    ips = _get_whitelist(deps)

    lines = ["\U0001f6e1\ufe0f <b>IP 白名单</b>", ""]

    if not ips:
        lines.append("白名单为空")
    else:
        for i, ip in enumerate(ips, 1):
            lines.append(f"  {i}. <code>{esc(ip)}</code>")

    lines.append("")
    lines.append("用法: /whitelist add|remove <ip>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def _whitelist_add(update, context, deps) -> None:
    """添加白名单 IP"""
    from .ban import validate_ip

    ip = context.args[1].strip()

    if not validate_ip(ip):
        await update.message.reply_text(
            format_error(f"无效的 IP 地址: {ip}"), parse_mode="HTML"
        )
        return

    ips = _get_whitelist(deps)
    if ip in ips:
        await update.message.reply_text(
            format_error(f"{ip} 已在白名单中"), parse_mode="HTML"
        )
        return

    ips.append(ip)
    _set_whitelist(deps, ips)

    await update.message.reply_text(
        format_success(f"已添加 {ip} 到白名单\n\n当前白名单共 {len(ips)} 个 IP"),
        parse_mode="HTML",
    )

    # 提醒需要 reload 生效
    if deps.f2b_manager is not None:
        await update.message.reply_text(
            "\u2139\ufe0f 提示：白名单已保存，执行 /reload 可使其生效。",
            parse_mode="HTML",
        )


async def _whitelist_remove(update, context, deps) -> None:
    """移除白名单 IP"""
    ip = context.args[1].strip()

    ips = _get_whitelist(deps)
    if ip not in ips:
        await update.message.reply_text(
            format_error(f"{ip} 不在白名单中"), parse_mode="HTML"
        )
        return

    ips.remove(ip)
    _set_whitelist(deps, ips)

    await update.message.reply_text(
        format_success(f"已从白名单移除 {ip}\n\n当前白名单共 {len(ips)} 个 IP"),
        parse_mode="HTML",
    )


# ──────────────────────────────────────────────
# /setnotify
# ──────────────────────────────────────────────

@require_operator
async def cmd_setnotify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setnotify on|off — 开关实时预警"""
    deps = get_deps(context)

    if not context.args:
        # 显示当前状态
        current = "on"
        if deps.db is not None:
            current = deps.db.get_config_override(KEY_NOTIFY_ENABLED, "on")

        status_icon = "\U0001f7e2" if current == "on" else "\U0001f534"
        await update.message.reply_text(
            f"{status_icon} <b>实时预警状态:</b> {current}\n\n"
            "用法: /setnotify on|off",
            parse_mode="HTML",
        )
        return

    arg = context.args[0].lower()

    if arg not in ("on", "off"):
        await update.message.reply_text(
            format_error("用法: /setnotify on|off"), parse_mode="HTML"
        )
        return

    if deps.db is None:
        await update.message.reply_text(
            format_error("状态库未加载，无法保存设置"), parse_mode="HTML"
        )
        return

    deps.db.set_config_override(KEY_NOTIFY_ENABLED, arg)

    status_icon = "\U0001f7e2" if arg == "on" else "\U0001f534"
    await update.message.reply_text(
        format_success(f"实时预警已{'开启' if arg == 'on' else '关闭'}"),
        parse_mode="HTML",
    )

    logger.info(f"实时预警设置为 {arg} (chat_id={update.effective_chat.id})")


# ──────────────────────────────────────────────
# /setschedule
# ──────────────────────────────────────────────

@require_admin
async def cmd_setschedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setschedule <type> <args> — 设置定时报告频率"""
    deps = get_deps(context)

    if not context.args:
        await _show_schedule(update, deps)
        return

    schedule_type = context.args[0].lower()

    if schedule_type == "daily":
        await _set_daily_schedule(update, context, deps)
    elif schedule_type == "weekly":
        await _set_weekly_schedule(update, context, deps)
    else:
        await update.message.reply_text(
            format_error(
                "用法:\n"
                "  /setschedule daily <HH:MM>\n"
                "  /setschedule weekly <day> <HH:MM>\n"
                "  /setschedule daily on|off\n"
                "  /setschedule weekly on|off\n\n"
                f"星期可选: {', '.join(VALID_DAYS)}"
            ),
            parse_mode="HTML",
        )


async def _show_schedule(update, deps) -> None:
    """显示当前定时报告设置"""
    lines = ["\u23f0 <b>定时报告设置</b>", ""]

    # 每日报告
    daily_enabled = deps.config.schedule.daily_report_enabled
    daily_time = deps.config.schedule.daily_report_time
    if deps.db is not None:
        en = deps.db.get_config_override(KEY_SCHEDULE_DAILY_ENABLED, "")
        if en:
            daily_enabled = en == "on"
        tm = deps.db.get_config_override(KEY_SCHEDULE_DAILY_TIME, "")
        if tm:
            daily_time = tm

    icon = "\u2705" if daily_enabled else "\u274c"
    lines.append(f"{icon} <b>每日报告:</b> {daily_time}")

    # 每周报告
    weekly_enabled = deps.config.schedule.weekly_report_enabled
    weekly_day = deps.config.schedule.weekly_report_day
    weekly_time = deps.config.schedule.weekly_report_time
    if deps.db is not None:
        en = deps.db.get_config_override(KEY_SCHEDULE_WEEKLY_ENABLED, "")
        if en:
            weekly_enabled = en == "on"
        tm = deps.db.get_config_override(KEY_SCHEDULE_WEEKLY_TIME, "")
        if tm:
            weekly_time = tm
        dy = deps.db.get_config_override(KEY_SCHEDULE_WEEKLY_DAY, "")
        if dy:
            weekly_day = dy

    icon = "\u2705" if weekly_enabled else "\u274c"
    lines.append(f"{icon} <b>每周报告:</b> {weekly_day} {weekly_time}")

    lines.append("")
    lines.append(
        "用法:\n"
        "  /setschedule daily <HH:MM>\n"
        "  /setschedule daily on|off\n"
        "  /setschedule weekly <day> <HH:MM>\n"
        "  /setschedule weekly on|off"
    )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def _validate_time(time_str: str) -> bool:
    """校验 HH:MM 格式"""
    try:
        parts = time_str.split(":")
        if len(parts) != 2:
            return False
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 23 and 0 <= m <= 59
    except (ValueError, IndexError):
        return False


async def _set_daily_schedule(update, context, deps) -> None:
    """设置每日报告时间"""
    if len(context.args) < 2:
        await update.message.reply_text(
            format_error("用法: /setschedule daily <HH:MM> 或 /setschedule daily on|off"),
            parse_mode="HTML",
        )
        return

    val = context.args[1]

    if val.lower() in ("on", "off"):
        if deps.db is None:
            await update.message.reply_text(
                format_error("状态库未加载"), parse_mode="HTML"
            )
            return
        deps.db.set_config_override(KEY_SCHEDULE_DAILY_ENABLED, val.lower())
        await update.message.reply_text(
            format_success(f"每日报告已{'开启' if val.lower() == 'on' else '关闭'}"),
            parse_mode="HTML",
        )
        return

    if not _validate_time(val):
        await update.message.reply_text(
            format_error(f"无效的时间格式: {val}\n请使用 HH:MM 格式，如 08:00"),
            parse_mode="HTML",
        )
        return

    if deps.db is None:
        await update.message.reply_text(
            format_error("状态库未加载，无法保存设置"), parse_mode="HTML"
        )
        return

    deps.db.set_config_override(KEY_SCHEDULE_DAILY_TIME, val)
    deps.db.set_config_override(KEY_SCHEDULE_DAILY_ENABLED, "on")

    await update.message.reply_text(
        format_success(f"每日报告已设置为 {val}，已自动开启"),
        parse_mode="HTML",
    )


async def _set_weekly_schedule(update, context, deps) -> None:
    """设置每周报告时间"""
    if len(context.args) < 2:
        await update.message.reply_text(
            format_error(
                "用法: /setschedule weekly <day> <HH:MM> 或 /setschedule weekly on|off"
            ),
            parse_mode="HTML",
        )
        return

    val = context.args[1]

    if val.lower() in ("on", "off"):
        if deps.db is None:
            await update.message.reply_text(
                format_error("状态库未加载"), parse_mode="HTML"
            )
            return
        deps.db.set_config_override(KEY_SCHEDULE_WEEKLY_ENABLED, val.lower())
        await update.message.reply_text(
            format_success(f"每周报告已{'开启' if val.lower() == 'on' else '关闭'}"),
            parse_mode="HTML",
        )
        return

    # 格式: /setschedule weekly monday 08:00
    if len(context.args) < 3:
        await update.message.reply_text(
            format_error("用法: /setschedule weekly <day> <HH:MM>\n"
                        f"星期可选: {', '.join(VALID_DAYS)}"),
            parse_mode="HTML",
        )
        return

    day = val.lower()
    time_str = context.args[2]

    if day not in VALID_DAYS:
        await update.message.reply_text(
            format_error(f"无效的星期: {day}\n可选: {', '.join(VALID_DAYS)}"),
            parse_mode="HTML",
        )
        return

    if not _validate_time(time_str):
        await update.message.reply_text(
            format_error(f"无效的时间格式: {time_str}\n请使用 HH:MM 格式，如 08:00"),
            parse_mode="HTML",
        )
        return

    if deps.db is None:
        await update.message.reply_text(
            format_error("状态库未加载，无法保存设置"), parse_mode="HTML"
        )
        return

    deps.db.set_config_override(KEY_SCHEDULE_WEEKLY_DAY, day)
    deps.db.set_config_override(KEY_SCHEDULE_WEEKLY_TIME, time_str)
    deps.db.set_config_override(KEY_SCHEDULE_WEEKLY_ENABLED, "on")

    await update.message.reply_text(
        format_success(f"每周报告已设置为 {day} {time_str}，已自动开启"),
        parse_mode="HTML",
    )
