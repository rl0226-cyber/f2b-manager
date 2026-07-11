"""
f2b_manager.telegram_bot.handlers.report
==========================================

报告与统计命令 handler。

命令:
    /report       — 生成即时报告
    /stats [days] — 统计 N 天封禁情况（默认 7 天）

权限: 操作员 (OPERATOR) 及以上
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..auth import require_operator
from ..deps import get_deps
from ..formatters import format_daily_stats, format_error, \
    format_stats_summary, format_status

logger = logging.getLogger(__name__)


@require_operator
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/report — 生成即时报告"""
    deps = get_deps(context)

    lines = ["\U0001f4cb <b>Fail2ban 即时报告</b>", ""]

    # 1. 服务状态
    if deps.f2b_manager is not None:
        try:
            status = deps.f2b_manager.get_status()
            lines.append(format_status(status))
        except Exception as e:
            logger.exception("获取状态失败")
            lines.append(f"\u26a0\ufe0f 获取状态失败: {e}")
    else:
        lines.append("\u26a0\ufe0f Fail2ban 管理模块未加载")

    lines.append("")

    # 2. 封禁统计
    if deps.db is not None:
        try:
            bans_today = deps.db.count_bans_today()
            lines.append(f"\U0001f6ab <b>今日封禁:</b> <code>{bans_today}</code>")

            current_bans = deps.db.get_current_bans()
            lines.append(
                f"\U0001f310 <b>当前在封:</b> <code>{len(current_bans)}</code> 个 IP"
            )

            # Top 5 攻击 IP（近 7 天）
            top_ips = deps.db.top_banned_ips(days=7, limit=5)
            if top_ips:
                lines.append("")
                lines.append("\U0001f525 <b>近 7 天 Top 攻击 IP:</b>")
                for i, (ip, count) in enumerate(top_ips, 1):
                    lines.append(f"  {i}. <code>{ip}</code> — <b>{count}</b> 次")

            # Top 5 来源国家
            top_countries = deps.db.top_banned_countries(days=7, limit=5)
            if top_countries:
                lines.append("")
                lines.append("\U0001f30d <b>近 7 天 Top 来源国家:</b>")
                for i, (country, count) in enumerate(top_countries, 1):
                    name = country or "未知"
                    lines.append(f"  {i}. {name} — <b>{count}</b> 次")
        except Exception as e:
            logger.exception("获取统计数据失败")
            lines.append(f"\u26a0\ufe0f 获取统计数据失败: {e}")
    else:
        lines.append("\u26a0\ufe0f 状态库未加载")

    lines.append("")
    lines.append(
        f"\U0001f552 <b>报告时间:</b> "
        f"{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@require_operator
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats [days] — 统计 N 天封禁情况"""
    deps = get_deps(context)

    if deps.db is None:
        await update.message.reply_text(
            format_error("状态库未加载，无法获取统计数据"), parse_mode="HTML"
        )
        return

    # 解析天数参数
    days = 7
    if context.args:
        try:
            days = int(context.args[0])
            if days < 1 or days > 365:
                await update.message.reply_text(
                    format_error("天数范围: 1-365"), parse_mode="HTML"
                )
                return
        except ValueError:
            await update.message.reply_text(
                format_error(f"无效的天数: {context.args[0]}"), parse_mode="HTML"
            )
            return

    try:
        # 获取每日统计
        daily_stats = deps.db.get_daily_stats(days=days)

        # 计算汇总
        total_bans = sum(s.total_bans for s in daily_stats)
        unique_ips = sum(s.unique_ips for s in daily_stats)

        # Top IP 和国家
        top_ips = deps.db.top_banned_ips(days=days, limit=10)
        top_countries = deps.db.top_banned_countries(days=days, limit=10)

        # 发送统计摘要
        await update.message.reply_text(
            format_stats_summary(
                total_bans=total_bans,
                unique_ips=unique_ips,
                top_ips=top_ips,
                top_countries=top_countries,
                days=days,
            ),
            parse_mode="HTML",
        )

        # 如果有每日统计，追加发送
        if daily_stats:
            await update.message.reply_text(
                format_daily_stats(daily_stats), parse_mode="HTML"
            )

    except Exception as e:
        logger.exception("获取统计失败")
        await update.message.reply_text(
            format_error(f"获取统计失败: {e}"), parse_mode="HTML"
        )
