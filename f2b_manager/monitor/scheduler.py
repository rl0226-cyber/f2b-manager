"""
f2b_manager.monitor.scheduler
==============================

定时任务调度器。

基于 APScheduler AsyncIOScheduler，管理 4 个定时任务:
1. 每日报告 (cron)          — 按配置时间生成并发送每日封禁报告
2. 每周报告 (cron)          — 按配置时间生成并发送每周统计报告
3. 轮询兜底 (interval)      — 对比封禁变化，补发遗漏通知
4. 健康检查 (interval)      — 检查 fail2ban 运行状态，异常时自动恢复

关键设计:
    AsyncIOScheduler 必须与 python-telegram-bot 的 Application 共享
    同一事件循环。start() 方法必须在事件循环运行后调用（即在 Bot.run()
    所创建的 asyncio 事件循环内调用）。

结合方式 (在 app.py 中):
    async def _main_loop(self):
        self._scheduler.setup_jobs()
        self._scheduler.start()       # ← 此时事件循环已在运行
        await self._bot.run()

    def run(self):
        asyncio.run(self._main_loop())
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import AppConfig
from ..storage.database import StateDB
from ..storage.models import (
    BanAction,
    BanEvent,
    IAlertSender,
    IFail2banManager,
    IMessageSender,
)
from ..utils.logger import get_logger
from .health import HealthChecker
from .reporter import BanReporter

logger = get_logger("monitor.scheduler")

# 星期映射: 配置值 → APScheduler cron day_of_week 缩写
_WEEKDAY_MAP: dict[str, str] = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat",
    "sunday": "sun",
    "mon": "mon", "tue": "tue", "wed": "wed",
    "thu": "thu", "fri": "fri", "sat": "sat", "sun": "sun",
}


class F2BScheduler:
    """基于 APScheduler AsyncIOScheduler 的定时任务调度器。

    管理 4 个定时任务，所有任务的时间配置均从 AppConfig.schedule 读取，
    支持运行时通过配置覆盖（StateDB config_overrides）动态修改。

    构造函数接收:
        config:        应用全局配置
        f2b_manager:   Fail2ban 运行时管理接口（可为 None，此时跳过轮询）
        bot:           消息发送接口（可为 None，此时仅记录日志）
        alert_sender:  预警发送接口（可为 None，此时跳过通知补发）
        db:            状态库接口（用于统计查询和快照对比）

    生命周期:
        scheduler = F2BScheduler(config, f2b, bot, alert, db)
        scheduler.setup_jobs()   # 注册任务（在事件循环创建后调用）
        scheduler.start()        # 启动调度（在事件循环运行后调用）
        scheduler.shutdown()     # 优雅关闭
    """

    def __init__(
        self,
        config: AppConfig,
        f2b_manager: Optional[IFail2banManager] = None,
        bot: Optional[IMessageSender] = None,
        alert_sender: Optional[IAlertSender] = None,
        db: Optional[StateDB] = None,
    ):
        self._config = config
        self._f2b = f2b_manager
        self._bot = bot
        self._alert_sender = alert_sender
        self._db = db

        # 子组件（仅在依赖可用时创建）
        if f2b_manager is not None and db is not None:
            self._reporter: Optional[BanReporter] = BanReporter(
                config, f2b_manager, db
            )
        else:
            self._reporter = None

        self._health_checker = HealthChecker(config, bot)

        # APScheduler 实例 — 在 setup_jobs() 中创建以确保使用正确的事件循环
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._started = False

    # ── 公共方法 ──────────────────────────────

    def setup_jobs(self) -> None:
        """注册所有定时任务。

        必须在事件循环存在后、start() 之前调用。
        创建 AsyncIOScheduler 实例并注册 4 个任务。
        所有时间参数从 self._config.schedule 读取。
        """
        self._scheduler = AsyncIOScheduler()
        sc = self._config.schedule

        # ── 任务1: 每日封禁报告 (cron) ──
        if sc.daily_report_enabled:
            hour, minute = self._parse_time(sc.daily_report_time)
            self._scheduler.add_job(
                self._daily_report_job,
                trigger="cron",
                hour=hour,
                minute=minute,
                id="daily_report",
                name="\u6bcf\u65e5\u5c01\u7981\u62a5\u544a",
                replace_existing=True,
            )
            logger.info(
                "\u5df2\u6ce8\u518c\u6bcf\u65e5\u62a5\u544a\u4efb\u52a1: %02d:%02d",
                hour, minute,
            )
        else:
            logger.info("\u6bcf\u65e5\u62a5\u544a\u5df2\u7981\u7528")

        # ── 任务2: 每周统计报告 (cron) ──
        if sc.weekly_report_enabled:
            weekday = _WEEKDAY_MAP.get(
                sc.weekly_report_day.lower(), "mon"
            )
            hour, minute = self._parse_time(sc.weekly_report_time)
            self._scheduler.add_job(
                self._weekly_report_job,
                trigger="cron",
                day_of_week=weekday,
                hour=hour,
                minute=minute,
                id="weekly_report",
                name="\u6bcf\u5468\u5c01\u7981\u7edf\u8ba1",
                replace_existing=True,
            )
            logger.info(
                "\u5df2\u6ce8\u518c\u6bcf\u5468\u62a5\u544a\u4efb\u52a1: %s %02d:%02d",
                sc.weekly_report_day, hour, minute,
            )
        else:
            logger.info("\u6bcf\u5468\u62a5\u544a\u5df2\u7981\u7528")

        # ── 任务3: 轮询兜底 (interval) ──
        self._scheduler.add_job(
            self._poll_ban_changes_job,
            trigger="interval",
            minutes=sc.poll_interval_minutes,
            id="poll_changes",
            name="\u8f6e\u8be2\u5c01\u7981\u53d8\u5316\u515c\u5e95",
            replace_existing=True,
        )
        logger.info(
            "\u5df2\u6ce8\u518c\u8f6e\u8be2\u515c\u5e95\u4efb\u52a1: \u6bcf %d \u5206\u949f",
            sc.poll_interval_minutes,
        )

        # ── 任务4: 健康检查 (interval) ──
        self._scheduler.add_job(
            self._health_check_job,
            trigger="interval",
            minutes=sc.health_check_minutes,
            id="health_check",
            name="Fail2ban \u5065\u5eb7\u68c0\u67e5",
            replace_existing=True,
        )
        logger.info(
            "\u5df2\u6ce8\u518c\u5065\u5eb7\u68c0\u67e5\u4efb\u52a1: \u6bcf %d \u5206\u949f",
            sc.health_check_minutes,
        )

    def start(self) -> None:
        """启动调度器。

        **关键**: 必须在 python-telegram-bot 的 asyncio 事件循环运行后调用。
        这样 APScheduler 才能与 Bot 共享同一个事件循环。

        典型调用方式（在 app.py 的 _main_loop 协程中）:
            self._scheduler.setup_jobs()
            self._scheduler.start()
            await self._bot.run()
        """
        if self._scheduler is None:
            logger.error("\u8c03\u5ea6\u5668\u672a\u521d\u59cb\u5316\uff0c\u8bf7\u5148\u8c03\u7528 setup_jobs()")
            return

        try:
            self._scheduler.start()
            self._started = True
            logger.info("APScheduler \u5df2\u542f\u52a8\uff0c\u6240\u6709\u5b9a\u65f6\u4efb\u52a1\u5df2\u6fc0\u6d3b")
        except Exception as e:
            logger.error("\u542f\u52a8\u8c03\u5ea6\u5668\u5931\u8d25: %s", e)
            raise

    def shutdown(self, wait: bool = True) -> None:
        """优雅关闭调度器。

        关闭前等待正在执行的任务完成（wait=True），
        或立即终止（wait=False）。

        Args:
            wait: 是否等待当前任务执行完。
        """
        if not self._started or self._scheduler is None:
            return

        logger.info("\u6b63\u5728\u5173\u95ed\u8c03\u5ea6\u5668...")
        try:
            self._scheduler.shutdown(wait=wait)
            self._started = False
            logger.info("\u8c03\u5ea6\u5668\u5df2\u5173\u95ed")
        except Exception as e:
            logger.error("\u5173\u95ed\u8c03\u5ea6\u5668\u5931\u8d25: %s", e)

    # ── 任务1: 每日报告 ────────────────────────

    async def _daily_report_job(self) -> None:
        """生成每日报告 → 通过 Bot 发送到 notify_chat_id。"""
        logger.info("\u6267\u884c\u6bcf\u65e5\u62a5\u544a\u4efb\u52a1...")

        if self._reporter is None:
            logger.warning("Reporter \u672a\u521d\u59cb\u5316\uff0c\u8df3\u8fc7\u6bcf\u65e5\u62a5\u544a")
            return

        try:
            report = self._reporter.daily_report()
            await self._send_report(report)
        except Exception as e:
            logger.error("\u6bcf\u65e5\u62a5\u544a\u4efb\u52a1\u5931\u8d25: %s", e, exc_info=True)

    # ── 任务2: 每周报告 ────────────────────────

    async def _weekly_report_job(self) -> None:
        """生成每周报告 → 通过 Bot 发送到 notify_chat_id。"""
        logger.info("\u6267\u884c\u6bcf\u5468\u62a5\u544a\u4efb\u52a1...")

        if self._reporter is None:
            logger.warning("Reporter \u672a\u521d\u59cb\u5316\uff0c\u8df3\u8fc7\u6bcf\u5468\u62a5\u544a")
            return

        try:
            report = self._reporter.weekly_report()
            await self._send_report(report)
        except Exception as e:
            logger.error("\u6bcf\u5468\u62a5\u544a\u4efb\u52a1\u5931\u8d25: %s", e, exc_info=True)

    # ── 任务3: 轮询兜底 ────────────────────────

    async def _poll_ban_changes_job(self) -> None:
        """轮询检测封禁变化，补发 Hook 遗漏的通知。

        Diff 算法:
        1. 遍历所有 jail，通过 get_jail_status() 获取每个 jail 的封禁 IP 列表
        2. 构建 current_bans: set[(ip, jail)]
        3. 从 StateDB 读取上次快照 saved_bans: set[(ip, jail)]
        4. 计算 diff:
           - added   = current_bans - saved_bans     (新增封禁)
           - removed = saved_bans - current_bans     (已解封)
        5. 对于每个 added IP → 构造 BanEvent → 调用 alert_sender.send_ban_alert()
        6. 对于每个 removed IP → 构造 BanEvent(UNBAN) → 调用 alert_sender.send_ban_alert()
        7. 更新 StateDB 快照: db.set_current_bans(current_bans)

        安全性：每个步骤独立 try/except，一个 jail 失败不影响其他 jail。
        """
        if self._f2b is None:
            logger.debug("f2b_manager \u672a\u914d\u7f6e\uff0c\u8df3\u8fc7\u8f6e\u8be2")
            return

        if self._db is None:
            logger.debug("db \u672a\u914d\u7f6e\uff0c\u8df3\u8fc7\u8f6e\u8be2")
            return

        logger.debug("\u6267\u884c\u8f6e\u8be2\u515c\u5e95...")

        try:
            # 步骤1: 获取当前所有封禁 (ip, jail)
            current_bans: list[tuple[str, str]] = []
            try:
                jails = self._f2b.get_jails()
                for jail_info in jails:
                    try:
                        jail_status = self._f2b.get_jail_status(jail_info.name)
                        for ip in jail_status.banned_ips:
                            current_bans.append((ip, jail_info.name))
                    except Exception as e:
                        logger.debug(
                            "\u83b7\u53d6 jail '%s' \u72b6\u6001\u5931\u8d25: %s",
                            jail_info.name, e,
                        )
            except Exception as e:
                logger.warning("\u83b7\u53d6\u5c01\u7981\u5217\u8868\u5931\u8d25: %s", e)
                return

            # 步骤2: 读取 DB 快照
            saved_bans = self._db.get_current_bans()

            # 步骤3: 计算 diff
            current_set: set[tuple[str, str]] = set(current_bans)
            saved_set: set[tuple[str, str]] = set(saved_bans)

            added = current_set - saved_set
            removed = saved_set - current_set

            if not added and not removed:
                logger.debug("\u8f6e\u8be2\u515c\u5e95: \u65e0\u53d8\u5316")
                return

            logger.info(
                "\u8f6e\u8be2\u515c\u5e95\u68c0\u6d4b\u5230\u53d8\u5316: +%d -%d",
                len(added), len(removed),
            )

            # 步骤4: 补发新增封禁通知
            if added and self._alert_sender is not None:
                for ip, jail in added:
                    try:
                        event = BanEvent(
                            ip=ip,
                            jail=jail,
                            action=BanAction.BAN,
                            timestamp=datetime.now(),
                        )
                        await self._alert_sender.send_ban_alert(event)
                        logger.info(
                            "\u8f6e\u8be2\u515c\u5e95\u8865\u53d1\u5c01\u7981\u901a\u77e5: ip=%s jail=%s",
                            ip, jail,
                        )
                    except Exception as e:
                        logger.error(
                            "\u8865\u53d1\u5c01\u7981\u901a\u77e5\u5931\u8d25 ip=%s: %s",
                            ip, e,
                        )

            # 步骤5: 补发解封通知
            if removed and self._alert_sender is not None:
                for ip, jail in removed:
                    try:
                        event = BanEvent(
                            ip=ip,
                            jail=jail,
                            action=BanAction.UNBAN,
                            timestamp=datetime.now(),
                        )
                        await self._alert_sender.send_ban_alert(event)
                        logger.info(
                            "\u8f6e\u8be2\u515c\u5e95\u8865\u53d1\u89e3\u5c01\u901a\u77e5: ip=%s jail=%s",
                            ip, jail,
                        )
                    except Exception as e:
                        logger.error(
                            "\u8865\u53d1\u89e3\u5c01\u901a\u77e5\u5931\u8d25 ip=%s: %s",
                            ip, e,
                        )

            # 步骤6: 更新 DB 快照
            self._db.set_current_bans(current_bans)
            logger.debug(
                "\u5df2\u66f4\u65b0 DB \u5feb\u7167: %d \u6761\u8bb0\u5f55",
                len(current_bans),
            )

        except Exception as e:
            logger.error("\u8f6e\u8be2\u515c\u5e95\u5f02\u5e38: %s", e, exc_info=True)

    # ── 任务4: 健康检查 ────────────────────────

    async def _health_check_job(self) -> None:
        """执行 fail2ban 健康检查。"""
        logger.debug("\u6267\u884c\u5065\u5eb7\u68c0\u67e5...")
        try:
            await self._health_checker.check()
        except Exception as e:
            logger.error("\u5065\u5eb7\u68c0\u67e5\u5f02\u5e38: %s", e, exc_info=True)

    # ── 内部辅助方法 ──────────────────────────

    async def _send_report(self, message: str) -> None:
        """通过 Bot 发送报告消息到配置的 notify_chat_id。

        bot 为 None 或 notify_chat_id 未设置时不报错，只记录日志。
        """
        if self._bot is None:
            logger.warning("bot \u672a\u914d\u7f6e\uff0c\u65e0\u6cd5\u53d1\u9001\u62a5\u544a")
            return

        chat_id = self._config.telegram.notify_chat_id
        if chat_id == 0:
            logger.warning("notify_chat_id \u672a\u8bbe\u7f6e\uff0c\u65e0\u6cd5\u53d1\u9001\u62a5\u544a")
            return

        try:
            await self._bot.send_report(chat_id=chat_id, message=message)
            logger.info("\u62a5\u544a\u5df2\u53d1\u9001\u81f3 chat_id=%d", chat_id)
        except Exception as e:
            logger.error("\u53d1\u9001\u62a5\u544a\u5931\u8d25: %s", e)

    @staticmethod
    def _parse_time(time_str: str) -> tuple[int, int]:
        """解析 "HH:MM" 格式的时间字符串。

        Args:
            time_str: 如 "08:00"、"14:30"

        Returns:
            (hour, minute) 元组。解析失败时返回 (8, 0)。
        """
        try:
            parts = time_str.strip().split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            # 边界校验
            hour = max(0, min(23, hour))
            minute = max(0, min(59, minute))
            return hour, minute
        except (ValueError, IndexError):
            logger.warning(
                "\u65f6\u95f4\u683c\u5f0f\u65e0\u6548 '%s'\uff0c\u4f7f\u7528\u9ed8\u8ba4 08:00",
                time_str,
            )
            return 8, 0

    # ── 属性 ──────────────────────────────────

    @property
    def is_running(self) -> bool:
        """调度器是否正在运行。"""
        return (
            self._started
            and self._scheduler is not None
            and self._scheduler.running
        )

    @property
    def reporter(self) -> Optional[BanReporter]:
        """获取 BanReporter 实例（可能为 None）。"""
        return self._reporter

    @property
    def health_checker(self) -> HealthChecker:
        """获取 HealthChecker 实例。"""
        return self._health_checker
