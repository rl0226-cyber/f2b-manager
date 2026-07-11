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
from ..keyboards import (
    CB_SCHEDULE, WEEKDAY_MAP,
    schedule_main_keyboard, schedule_time_keyboard, schedule_weekday_keyboard,
)

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
    """/setschedule — 定时报告按钮设置面板"""
    await _show_schedule_panel(update, context)


async def handle_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理定时报告设置的所有按钮回调"""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    deps = get_deps(context)

    if not data.startswith(CB_SCHEDULE):
        return

    action = data[len(CB_SCHEDULE) + 1:]  # 去掉 "sch_"

    if action == "del":
        await query.delete_message()
        return

    if action == "main":
        await _refresh_panel(query, deps)
        return

    if action == "tog_d":
        await _toggle_schedule(query, deps, "daily")
        return

    if action == "tog_w":
        await _toggle_schedule(query, deps, "weekly")
        return

    if action == "timed":
        await _show_time_picker(query, "daily")
        return

    if action == "timew":
        await _show_time_picker(query, "weekly")
        return

    if action == "dayw":
        await _show_day_picker(query, deps)
        return

    # 设置时间: sch_tm_daily:08:00 或 sch_tm_weekly:12:00
    if action.startswith("tm_"):
        rest = action[3:]  # "daily:08:00" 或 "weekly:12:00"
        target, _, time_str = rest.partition(":")
        await _set_time(query, deps, target, time_str)
        return

    # 设置星期: sch_dy_monday
    if action.startswith("dy_"):
        day = action[3:]
        await _set_weekday(query, deps, day)
        return


# ── 内部辅助函数 ──────────────────────────────

def _read_schedule(deps) -> dict:
    """读取当前定时报告设置，返回 dict"""
    cfg = deps.config.schedule
    result = {
        "daily_enabled": cfg.daily_report_enabled,
        "daily_time": cfg.daily_report_time,
        "weekly_enabled": cfg.weekly_report_enabled,
        "weekly_day": cfg.weekly_report_day,
        "weekly_time": cfg.weekly_report_time,
    }
    if deps.db is not None:
        en = deps.db.get_config_override(KEY_SCHEDULE_DAILY_ENABLED, "")
        if en:
            result["daily_enabled"] = en == "on"
        tm = deps.db.get_config_override(KEY_SCHEDULE_DAILY_TIME, "")
        if tm:
            result["daily_time"] = tm
        en = deps.db.get_config_override(KEY_SCHEDULE_WEEKLY_ENABLED, "")
        if en:
            result["weekly_enabled"] = en == "on"
        tm = deps.db.get_config_override(KEY_SCHEDULE_WEEKLY_TIME, "")
        if tm:
            result["weekly_time"] = tm
        dy = deps.db.get_config_override(KEY_SCHEDULE_WEEKLY_DAY, "")
        if dy:
            result["weekly_day"] = dy
    return result


async def _show_schedule_panel(update, context, from_callback: bool = False) -> None:
    """显示定时报告设置面板（按钮模式）"""
    deps = get_deps(context)
    s = _read_schedule(deps)

    text = "⏰ <b>定时报告设置</b>"
    keyboard = schedule_main_keyboard(
        daily_enabled=s["daily_enabled"],
        daily_time=s["daily_time"],
        weekly_enabled=s["weekly_enabled"],
        weekly_day=s["weekly_day"],
        weekly_time=s["weekly_time"],
    )

    if from_callback:
        query = update.callback_query
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def _refresh_panel(query, deps) -> None:
    """刷新面板（保持当前菜单）"""
    s = _read_schedule(deps)
    text = "⏰ <b>定时报告设置</b>"
    keyboard = schedule_main_keyboard(
        daily_enabled=s["daily_enabled"],
        daily_time=s["daily_time"],
        weekly_enabled=s["weekly_enabled"],
        weekly_day=s["weekly_day"],
        weekly_time=s["weekly_time"],
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


async def _show_time_picker(query, target: str) -> None:
    """显示时间选择键盘"""
    label = "每日" if target == "daily" else "每周"
    text = f"🕐 <b>选择{label}报告时间</b>"
    keyboard = schedule_time_keyboard(target)
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


async def _show_day_picker(query, deps) -> None:
    """显示星期选择键盘"""
    s = _read_schedule(deps)
    text = "📅 <b>选择每周报告星期</b>"
    keyboard = schedule_weekday_keyboard(s["weekly_day"])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


async def _toggle_schedule(query, deps, target: str) -> None:
    """切换报告开关"""
    if deps.db is None:
        await query.answer("状态库未加载", show_alert=True)
        return

    if target == "daily":
        key_en = KEY_SCHEDULE_DAILY_ENABLED
        label = "每日报告"
    else:
        key_en = KEY_SCHEDULE_WEEKLY_ENABLED
        label = "每周报告"

    current = deps.db.get_config_override(key_en, "")
    if not current:
        # 从 config 读默认值
        cfg = deps.config.schedule
        current = "on" if (cfg.daily_report_enabled if target == "daily" else cfg.weekly_report_enabled) else "off"

    new_val = "off" if current == "on" else "on"
    deps.db.set_config_override(key_en, new_val)

    await query.answer(f"{label}已{'开启' if new_val == 'on' else '关闭'}")
    await _refresh_panel(query, deps)


async def _set_time(query, deps, target: str, time_str: str) -> None:
    """设置报告时间"""
    if deps.db is None:
        await query.answer("状态库未加载", show_alert=True)
        return

    if not _validate_time(time_str):
        await query.answer(f"无效时间: {time_str}", show_alert=True)
        return

    if target == "daily":
        deps.db.set_config_override(KEY_SCHEDULE_DAILY_TIME, time_str)
        deps.db.set_config_override(KEY_SCHEDULE_DAILY_ENABLED, "on")
    else:
        deps.db.set_config_override(KEY_SCHEDULE_WEEKLY_TIME, time_str)
        deps.db.set_config_override(KEY_SCHEDULE_WEEKLY_ENABLED, "on")

    await query.answer(f"{'每日' if target == 'daily' else '每周'}报告时间已设为 {time_str}")
    await _refresh_panel(query, deps)


async def _set_weekday(query, deps, day: str) -> None:
    """设置每周报告星期"""
    if deps.db is None:
        await query.answer("状态库未加载", show_alert=True)
        return

    if day not in VALID_DAYS:
        await query.answer(f"无效星期: {day}", show_alert=True)
        return

    deps.db.set_config_override(KEY_SCHEDULE_WEEKLY_DAY, day)
    deps.db.set_config_override(KEY_SCHEDULE_WEEKLY_ENABLED, "on")

    for eng, chn in WEEKDAY_MAP:
        if eng == day:
            await query.answer(f"每周报告已设为 {chn} " + _read_schedule(deps)["weekly_time"])
            break

    await _refresh_panel(query, deps)


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
