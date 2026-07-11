"""
f2b_manager.monitor.reporter
=============================

报告生成器。

实现 IReporter 协议，生成每日/每周/即时封禁情况报告。
数据来源：StateDB 统计查询 + Fail2banManager 状态接口。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from ..config import AppConfig
from ..storage.database import StateDB
from ..storage.models import (
    IFail2banManager,
    ServiceState,
)

logger = logging.getLogger("monitor.reporter")


def _fmt_time(dt: Optional[datetime] = None) -> str:
    """格式化时间为可读字符串。"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_date(dt: Optional[datetime] = None) -> str:
    """格式化日期为 YYYY-MM-DD。"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d")


def _state_emoji(state: ServiceState) -> str:
    """服务状态 → 彩色圆点 emoji。"""
    if state == ServiceState.RUNNING:
        return "\U0001f7e2"  # 🟢
    elif state == ServiceState.STOPPED:
        return "\U0001f534"  # 🔴
    return "\U0001f7e1"  # 🟡


def _bar_chart(count: int, max_width: int = 20) -> str:
    """生成简易柱状图字符串。"""
    return "\u2588" * min(count, max_width)


class BanReporter:
    """封禁情况报告生成器，实现 IReporter 协议。

    构造函数接收:
        config: 应用全局配置（用于读取 fail2ban 配置摘要）
        f2b_manager: Fail2ban 运行时管理接口
        db: 状态库接口（统计查询）

    Usage:
        reporter = BanReporter(config, f2b_manager, db)
        daily = reporter.daily_report()     # 每日报告文本
        weekly = reporter.weekly_report()   # 每周报告文本
        instant = reporter.instant_report() # 即时快照
    """

    def __init__(
        self,
        config: AppConfig,
        f2b_manager: IFail2banManager,
        db: StateDB,
    ):
        self._config = config
        self._f2b = f2b_manager
        self._db = db

    # ── IReporter 协议实现 ─────────────────────

    def daily_report(self) -> str:
        """生成每日报告 HTML 文本。

        内容包括:
        - 服务状态（版本、运行状态、Jail 数量）
        - 今日封禁统计（封禁次数、当前在封 IP 数）
        - Top 5 攻击来源 IP
        - Top 5 攻击来源国家
        - 各 Jail 状态（当前封禁数、失败次数）
        - Fail2ban 配置摘要

        Returns:
            格式化的 HTML 报告文本（用于 Telegram 发送）。
        """
        # ── 获取数据 ──
        try:
            status = self._f2b.get_status()
        except Exception as e:
            logger.warning("获取 fail2ban 状态失败: %s", e)
            status = None

        bans_today = self._db.count_bans_today()
        current_bans = self._db.get_current_bans()
        top_ips = self._db.top_banned_ips(days=1, limit=5)
        top_countries = self._db.top_banned_countries(days=1, limit=5)

        try:
            jails = self._f2b.get_jails()
        except Exception as e:
            logger.warning("获取 jail 列表失败: %s", e)
            jails = []

        today = _fmt_date()

        # ── 组装报告 ──
        lines: list[str] = []
        lines.append("<b>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501</b>")
        lines.append(f"<b>\U0001f4ca Fail2ban \u6bcf\u65e5\u62a5\u544a {today}</b>")
        lines.append("<b>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501</b>")
        lines.append("")

        # 服务状态
        if status is not None:
            emoji = _state_emoji(status.state)
            lines.append(f"{emoji} <b>\u670d\u52a1\u72b6\u6001:</b> {status.state.value}")
            if status.version:
                lines.append(f"\U0001f4e6 <b>\u7248\u672c:</b> {status.version}")
            if status.jail_count:
                lines.append(f"\U0001f512 <b>Jail \u6570\u91cf:</b> {status.jail_count}")
        else:
            lines.append("\U0001f534 <b>\u670d\u52a1\u72b6\u6001:</b> \u65e0\u6cd5\u83b7\u53d6")

        lines.append("")

        # 今日封禁统计
        lines.append("<b>\U0001f6ab \u4eca\u65e5\u5c01\u7981\u7edf\u8ba1:</b>")
        lines.append(f"  \u2022 \u603b\u5c01\u7981\u6b21\u6570: <b>{bans_today}</b>")
        lines.append(f"  \u2022 \u5f53\u524d\u5728\u5c01: <b>{len(current_bans)}</b> \u4e2a IP")

        # Top 攻击来源 IP
        if top_ips:
            lines.append("")
            lines.append("<b>\U0001f3af Top \u653b\u51fb\u6765\u6e90 (\u4eca\u65e5):</b>")
            for i, (ip, count) in enumerate(top_ips, 1):
                country = self._get_ip_country(ip)
                country_display = f" ({country})" if country else ""
                lines.append(
                    f"  {i}. <code>{ip}</code>{country_display} - "
                    f"<b>{count}</b> \u6b21"
                )

        # Top 攻击来源国家
        if top_countries:
            lines.append("")
            lines.append("<b>\U0001f310 Top \u653b\u51fb\u6765\u6e90\u56fd\u5bb6:</b>")
            for i, (country, count) in enumerate(top_countries, 1):
                country_display = country if country else "\u672a\u77e5"
                lines.append(f"  {i}. {country_display} - <b>{count}</b> \u6b21")

        # 各 Jail 状态
        if jails:
            lines.append("")
            lines.append("<b>\U0001f512 \u5404 Jail \u72b6\u6001:</b>")
            for jail in jails:
                lines.append(
                    f"  \u2022 <code>{jail.name}</code>: "
                    f"\u5c01\u7981 {jail.current_ban} / "
                    f"\u5931\u8d25 {jail.total_failed}"
                )

        # 配置摘要
        lines.append("")
        lines.append("<b>\u2699\ufe0f \u914d\u7f6e:</b>")
        f2b_cfg = self._config.fail2ban
        lines.append(f"  \u2022 bantime: {f2b_cfg.default_bantime}")
        lines.append(f"  \u2022 maxretry: {f2b_cfg.default_maxretry}")
        lines.append(f"  \u2022 findtime: {f2b_cfg.default_findtime}")

        lines.append("")
        lines.append("<b>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501</b>")
        lines.append(f"<i>\u751f\u6210\u65f6\u95f4: {_fmt_time()}</i>")

        return "\n".join(lines)

    def weekly_report(self) -> str:
        """生成每周报告 HTML 文本。

        内容包括:
        - 服务状态
        - 本周总览（总封禁次数、独立攻击 IP、当前在封）
        - 每日封禁趋势（柱状图）
        - Top 10 攻击来源 IP
        - Top 5 攻击来源国家

        Returns:
            格式化的 HTML 报告文本。
        """
        today = _fmt_date()
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        # ── 获取数据 ──
        try:
            status = self._f2b.get_status()
        except Exception as e:
            logger.warning("获取 fail2ban 状态失败: %s", e)
            status = None

        daily_stats = self._db.get_daily_stats(days=7)
        top_ips = self._db.top_banned_ips(days=7, limit=10)
        top_countries = self._db.top_banned_countries(days=7, limit=5)

        # 计算周汇总
        total_weekly_bans = sum(s.total_bans for s in daily_stats)
        total_weekly_ips = sum(s.unique_ips for s in daily_stats)
        current_bans = self._db.get_current_bans()

        # ── 组装报告 ──
        lines: list[str] = []
        lines.append("<b>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501</b>")
        lines.append("<b>\U0001f4ca Fail2ban \u6bcf\u5468\u62a5\u544a</b>")
        lines.append(f"<b>{week_ago} ~ {today}</b>")
        lines.append("<b>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501</b>")
        lines.append("")

        # 服务状态
        if status is not None:
            emoji = _state_emoji(status.state)
            lines.append(f"{emoji} <b>\u670d\u52a1\u72b6\u6001:</b> {status.state.value}")
            lines.append(f"\U0001f4e6 <b>\u7248\u672c:</b> {status.version}")
        else:
            lines.append("\U0001f534 <b>\u670d\u52a1\u72b6\u6001:</b> \u65e0\u6cd5\u83b7\u53d6")

        lines.append("")

        # 本周总览
        lines.append("<b>\U0001f4ca \u672c\u5468\u603b\u89c8:</b>")
        lines.append(f"  \u2022 \u603b\u5c01\u7981\u6b21\u6570: <b>{total_weekly_bans}</b>")
        lines.append(f"  \u2022 \u72ec\u7acb\u653b\u51fb IP: <b>{total_weekly_ips}</b>")
        lines.append(f"  \u2022 \u5f53\u524d\u5728\u5c01: <b>{len(current_bans)}</b> \u4e2a")

        # 每日趋势（带柱状图）
        if daily_stats:
            lines.append("")
            lines.append("<b>\U0001f4c8 \u6bcf\u65e5\u5c01\u7981\u8d8b\u52bf:</b>")
            max_bans = max((s.total_bans for s in daily_stats), default=1)
            for stat in daily_stats:
                bar_width = int(stat.total_bans / max_bans * 20) if max_bans > 0 else 0
                bar = _bar_chart(bar_width)
                lines.append(
                    f"  <code>{stat.date}</code> {bar} "
                    f"<b>{stat.total_bans}</b> \u6b21 "
                    f"({stat.unique_ips} IP)"
                )

        # Top 攻击来源 IP
        if top_ips:
            lines.append("")
            lines.append("<b>\U0001f3af Top \u653b\u51fb\u6765\u6e90 (\u672c\u5468):</b>")
            for i, (ip, count) in enumerate(top_ips, 1):
                country = self._get_ip_country(ip)
                country_display = f" ({country})" if country else ""
                lines.append(
                    f"  {i}. <code>{ip}</code>{country_display} - "
                    f"<b>{count}</b> \u6b21"
                )

        # Top 攻击来源国家
        if top_countries:
            lines.append("")
            lines.append("<b>\U0001f310 Top \u653b\u51fb\u6765\u6e90\u56fd\u5bb6:</b>")
            for i, (country, count) in enumerate(top_countries, 1):
                country_display = country if country else "\u672a\u77e5"
                lines.append(f"  {i}. {country_display} - <b>{count}</b> \u6b21")

        lines.append("")
        lines.append("<b>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
                      "\u2501\u2501\u2501\u2501\u2501\u2501</b>")
        lines.append(f"<i>\u751f\u6210\u65f6\u95f4: {_fmt_time()}</i>")

        return "\n".join(lines)

    def instant_report(self) -> str:
        """生成即时报告，供 /report 命令调用。

        精简版快照，适合即时查看。包含:
        - 服务状态
        - 今日封禁次数 + 当前在封数
        - Top 3 高频攻击 IP

        Returns:
            格式化的 HTML 报告文本。
        """
        # ── 获取数据 ──
        try:
            status = self._f2b.get_status()
        except Exception as e:
            logger.warning("获取 fail2ban 状态失败: %s", e)
            status = None

        bans_today = self._db.count_bans_today()
        current_bans = self._db.get_current_bans()
        top_ips = self._db.top_banned_ips(days=1, limit=3)

        # ── 组装报告 ──
        lines: list[str] = []
        lines.append("<b>\U0001f4ca Fail2ban \u5373\u65f6\u62a5\u544a</b>")
        lines.append("")

        if status is not None:
            emoji = _state_emoji(status.state)
            parts = [f"{emoji} \u72b6\u6001: {status.state.value}"]
            if status.version:
                parts.append(f"\u7248\u672c: {status.version}")
            if status.jail_count:
                parts.append(f"Jail: {status.jail_count} \u4e2a")
            lines.append(" | ".join(parts))
        else:
            lines.append("\U0001f534 \u72b6\u6001: \u65e0\u6cd5\u83b7\u53d6")

        lines.append(
            f"\U0001f6ab \u4eca\u65e5\u5c01\u7981: <b>{bans_today}</b> \u6b21 | "
            f"\u5f53\u524d\u5728\u5c01: <b>{len(current_bans)}</b> \u4e2a"
        )

        if top_ips:
            ips_parts = []
            for ip, cnt in top_ips:
                ips_parts.append(f"<code>{ip}</code>({cnt})")
            lines.append(f"\U0001f3af \u9ad8\u9891\u653b\u51fb: {', '.join(ips_parts)}")

        lines.append(f"\n<i>\u751f\u6210\u65f6\u95f4: {_fmt_time()}</i>")

        return "\n".join(lines)

    # ── 内部方法 ──────────────────────────────

    def _get_ip_country(self, ip: str) -> str:
        """从封禁历史中查询 IP 所属国家。

        Args:
            ip: IP 地址

        Returns:
            国家名称，未找到返回空字符串。
        """
        try:
            history = self._db.get_ban_history(days=30)
            for event in history:
                if event.ip == ip and event.country:
                    return event.country
        except Exception as e:
            logger.debug("查询 IP 所属国家失败 ip=%s: %s", ip, e)
        return ""
