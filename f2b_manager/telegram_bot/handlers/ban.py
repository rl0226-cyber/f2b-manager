"""
f2b_manager.telegram_bot.handlers.ban
======================================

封禁管理命令 handler。

命令:
    /ban <ip> [jail]    — 手动封禁 IP（默认 jail: sshd）
    /unban <ip>         — 解封 IP

权限: 管理员 (ADMIN)
"""

from __future__ import annotations

import ipaddress
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..auth import require_admin
from ..deps import get_deps
from ..formatters import format_ban_result, format_error, format_not_ready

logger = logging.getLogger(__name__)


def validate_ip(ip_str: str) -> bool:
    """校验 IP 地址格式（支持 IPv4 / IPv6）"""
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False


def _usage_ban() -> str:
    return (
        "用法:\n"
        "  <code>/ban &lt;ip&gt; [jail]</code>\n\n"
        "示例:\n"
        "  /ban 1.2.3.4\n"
        "  /ban 1.2.3.4 sshd"
    )


def _usage_unban() -> str:
    return (
        "用法:\n"
        "  <code>/unban &lt;ip&gt;</code>\n\n"
        "示例:\n"
        "  /unban 1.2.3.4"
    )


@require_admin
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ban <ip> [jail] — 手动封禁 IP"""
    deps = get_deps(context)

    if deps.f2b_manager is None:
        await update.message.reply_text(format_not_ready(), parse_mode="HTML")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            f"\u274c <b>参数缺失</b>\n\n{_usage_ban()}", parse_mode="HTML"
        )
        return

    ip = args[0].strip()

    # IP 格式校验
    if not validate_ip(ip):
        await update.message.reply_text(
            format_error(f"无效的 IP 地址: {ip}\n\n{_usage_ban()}"),
            parse_mode="HTML",
        )
        return

    # 可选 jail 参数
    jail = "sshd"
    if len(args) > 1:
        jail = args[1].strip()

    try:
        success = deps.f2b_manager.ban_ip(ip, jail)
        await update.message.reply_text(
            format_ban_result(ip, jail, success, "封禁"),
            parse_mode="HTML",
        )
        logger.info(f"手动封禁 IP={ip} jail={jail} success={success}")
    except Exception as e:
        logger.exception(f"封禁 IP {ip} 失败")
        await update.message.reply_text(
            format_error(f"封禁 IP {ip} 失败: {e}"), parse_mode="HTML"
        )


@require_admin
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unban <ip> — 解封 IP"""
    deps = get_deps(context)

    if deps.f2b_manager is None:
        await update.message.reply_text(format_not_ready(), parse_mode="HTML")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            f"\u274c <b>参数缺失</b>\n\n{_usage_unban()}", parse_mode="HTML"
        )
        return

    ip = args[0].strip()

    # IP 格式校验
    if not validate_ip(ip):
        await update.message.reply_text(
            format_error(f"无效的 IP 地址: {ip}\n\n{_usage_unban()}"),
            parse_mode="HTML",
        )
        return

    try:
        # 先查 IP 属于哪个 jail
        jail = "-"
        try:
            for j in deps.f2b_manager.get_jails():
                js = deps.f2b_manager.get_jail_status(j.name)
                if ip in js.banned_ips:
                    jail = j.name
                    break
        except Exception:
            pass  # 查询失败也不影响解封

        success = deps.f2b_manager.unban_ip(ip)
        await update.message.reply_text(
            format_ban_result(ip, jail, success, "解封"),
            parse_mode="HTML",
        )
        logger.info(f"手动解封 IP={ip} success={success}")
    except Exception as e:
        logger.exception(f"解封 IP {ip} 失败")
        await update.message.reply_text(
            format_error(f"解封 IP {ip} 失败: {e}"), parse_mode="HTML"
        )
