"""
f2b_manager.telegram_bot.handlers.status
=========================================

状态查询命令 handler。

命令:
    /status       — Fail2ban 运行状态总览
    /jails        — 列出所有 jail
    /banned       — 列出当前被封禁 IP
    /jail <name>  — 查看指定 jail 详情

权限: 操作员 (OPERATOR) 及以上
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..auth import require_operator
from ..deps import get_deps
from ..formatters import format_banned_ips, format_error, format_jail_detail, \
    format_jails, format_not_ready, format_status

logger = logging.getLogger(__name__)


@require_operator
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — Fail2ban 运行状态总览"""
    deps = get_deps(context)

    if deps.f2b_manager is None:
        await update.message.reply_text(format_not_ready(), parse_mode="HTML")
        return

    try:
        status = deps.f2b_manager.get_status()
        await update.message.reply_text(
            format_status(status), parse_mode="HTML"
        )
    except Exception as e:
        logger.exception("获取状态失败")
        await update.message.reply_text(
            format_error(f"获取状态失败: {e}"), parse_mode="HTML"
        )


@require_operator
async def cmd_jails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/jails — 列出所有 jail"""
    deps = get_deps(context)

    if deps.f2b_manager is None:
        await update.message.reply_text(format_not_ready(), parse_mode="HTML")
        return

    try:
        jails = deps.f2b_manager.get_jails()
        await update.message.reply_text(
            format_jails(jails), parse_mode="HTML"
        )
    except Exception as e:
        logger.exception("获取 jail 列表失败")
        await update.message.reply_text(
            format_error(f"获取 jail 列表失败: {e}"), parse_mode="HTML"
        )


@require_operator
async def cmd_banned(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/banned — 列出当前所有被封禁 IP（含国家归属）"""
    deps = get_deps(context)

    if deps.f2b_manager is None:
        await update.message.reply_text(format_not_ready(), parse_mode="HTML")
        return

    try:
        ips = deps.f2b_manager.get_banned_ips()

        # 查询国家归属
        countries: dict[str, str] = {}
        if ips and deps.config.notify.geoip_enabled:
            try:
                from ...notify.geoip import GeoIPLookup
                geo = GeoIPLookup(
                    db_path=deps.config.notify.geoip_db_path,
                    method=deps.config.notify.geoip_method,
                )
                for ip in ips:
                    info = await geo.lookup(ip)
                    if info.country:
                        flag = f" {info.flag}" if info.flag else ""
                        countries[ip] = f"{info.country}{flag}"
                geo.close()
            except Exception:
                pass  # 查询失败不影响列表显示

        await update.message.reply_text(
            format_banned_ips(ips, countries), parse_mode="HTML"
        )
    except Exception as e:
        logger.exception("获取封禁 IP 列表失败")
        await update.message.reply_text(
            format_error(f"获取封禁列表失败: {e}"), parse_mode="HTML"
        )


@require_operator
async def cmd_jail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/jail <name> — 查看指定 jail 详情"""
    deps = get_deps(context)

    if deps.f2b_manager is None:
        await update.message.reply_text(format_not_ready(), parse_mode="HTML")
        return

    # 参数校验
    args = context.args
    if not args:
        await update.message.reply_text(
            format_error("用法: /jail <jail_name>\n例如: /jail sshd"),
            parse_mode="HTML",
        )
        return

    jail_name = args[0].strip()

    try:
        jail_status = deps.f2b_manager.get_jail_status(jail_name)
        await update.message.reply_text(
            format_jail_detail(jail_status), parse_mode="HTML"
        )
    except Exception as e:
        logger.exception(f"获取 jail '{jail_name}' 详情失败")
        await update.message.reply_text(
            format_error(f"获取 jail '{jail_name}' 详情失败: {e}"),
            parse_mode="HTML",
        )
