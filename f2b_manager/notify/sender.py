"""
f2b_manager.notify.sender
=========================

预警消息构造与发送。

实现 IAlertSender 协议，负责:
1. 查询 IP 归属地（GeoIPLookup）
2. 去重检查（DedupTracker）
3. 构造 HTML 格式预警消息
4. 通过 Telegram Bot 发送消息
5. 记录封禁事件到状态库

bot 参数可为 None（独立开发/测试阶段），此时只记录日志不发送。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from ..config import AppConfig
from ..storage.models import (
    BanAction, BanEvent, GeoInfo, IAlertSender, IMessageSender, IStateDB,
)

logger = logging.getLogger("notify.sender")

# ── 消息模板 ────────────────────────────────

BAN_TEMPLATE = """\
<b>IP 封禁预警</b>
----------------------
Jail: <code>{jail}</code>
IP: <code>{ip}</code>
归属: {country} {flag}
失败次数: <b>{failures}</b>
时间: {time}
匹配日志:
<pre>{matches_preview}</pre>
----------------------
当前总封禁: {total_banned} 个 IP"""

UNBAN_TEMPLATE = """\
<b>IP 已解封</b>
----------------------
IP: <code>{ip}</code>
Jail: {jail}
解封时间: {time}
封禁时长: {ban_duration}"""

SERVICE_START_TEMPLATE = """\
<b>Fail2ban 服务启动</b>
----------------------
Jail: {jail}
时间: {time}"""

SERVICE_STOP_TEMPLATE = """\
<b>Fail2ban 服务停止</b>
----------------------
Jail: {jail}
时间: {time}"""


def _format_time(dt: Optional[datetime] = None) -> str:
    """格式化时间为可读字符串。"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _truncate_matches(matches: str, max_length: int = 200) -> str:
    """截断匹配日志，避免消息过长。"""
    if not matches:
        return "(无)"
    if len(matches) <= max_length:
        return matches
    return matches[:max_length] + "...(已截断)"


def _estimate_ban_duration(event: BanEvent) -> str:
    """估算封禁时长（基于封禁/解封时间差）。

    由于 notify.sh 只传入当前事件，无法精确计算时长。
    对于 unban 事件，记录从封禁到解封的估算值。
    如果 event 没有记录封禁时间，返回 "未知"。
    """
    # 从 event.timestamp 估算（这里只能给出当前时间，实际时长需从 db 查询）
    return "未知"


class AlertSender:
    """预警消息发送器，实现 IAlertSender 协议。

    构造时注入:
    - config: 应用全局配置（用于读取 notify 开关、dedup 窗口等）
    - bot: 消息发送接口（Telegram Bot），可为 None（开发模式）
    - db: 状态库接口（用于记录事件、查询统计）
    """

    def __init__(
        self,
        config: AppConfig,
        bot: Optional[IMessageSender] = None,
        db: Optional[IStateDB] = None,
    ):
        self._config = config
        self._bot = bot
        self._db = db

        # 延迟导入，避免循环依赖
        from .geoip import GeoIPLookup
        from .dedup import DedupTracker

        self._geoip = GeoIPLookup(
            db_path=config.notify.geoip_db_path,
            method=config.notify.geoip_method,
        )
        self._dedup = DedupTracker(
            window_seconds=config.notify.dedup_window_seconds,
        )

    # ── IAlertSender 协议实现 ─────────────────

    async def send_ban_alert(self, event: BanEvent) -> bool:
        """发送封禁/解封预警。

        处理流程:
        1. 查询 IP 归属地（始终执行，用于存库）
        2. 记录到状态库（始终执行，便于统计/审计）
        3. 去重检查（仅 ban 事件）
        4. 检查通知开关
        5. 构造 HTML 消息 → 发送（bot 可用时）

        Args:
            event: 封禁/解封事件

        Returns:
            True 表示处理成功（包括被去重/开关关闭/正常发送），
            False 表示处理过程中出现错误。
        """
        ncfg = self._config.notify

        # 步骤1: 查询 IP 归属地（始终执行，便于存库和统计）
        geo_info: GeoInfo = GeoInfo()
        if ncfg.geoip_enabled:
            try:
                geo_info = await self._geoip.lookup(event.ip)
            except Exception as e:
                logger.warning("GeoIP 查询异常 ip=%s: %s", event.ip, e)

        # 更新 event 的 country 字段（便于存库）
        event.country = geo_info.country or geo_info.country_code

        # 步骤2: 记录到状态库（无论是否发送通知都记录，便于统计审计）
        self._record_event(event, geo_info)

        # 步骤3: 去重检查（仅 ban 事件需要去重）
        if event.action == BanAction.BAN:
            if not self._dedup.should_send(event.ip, event.jail):
                logger.info(
                    "封禁事件被去重: ip=%s jail=%s (窗口=%d秒)",
                    event.ip, event.jail,
                    ncfg.dedup_window_seconds,
                )
                return True

        # 步骤4: 检查通知开关
        if event.action == BanAction.BAN and not ncfg.enable_ban_alert:
            logger.debug("封禁通知已关闭，跳过发送 ip=%s", event.ip)
            return True

        if event.action == BanAction.UNBAN and not ncfg.enable_unban_alert:
            logger.debug("解封通知已关闭，跳过发送 ip=%s", event.ip)
            return True

        # 步骤5: 构造消息并发送
        message = self._build_message(event, geo_info)
        sent = await self._send_message(message)

        if sent:
            logger.info(
                "已发送预警: action=%s ip=%s jail=%s",
                event.action.value, event.ip, event.jail,
            )
        else:
            logger.warning(
                "预警未发送(bot不可用): action=%s ip=%s jail=%s",
                event.action.value, event.ip, event.jail,
            )

        return True

    async def send_service_alert(self, action: BanAction,
                                 jail: str = "") -> bool:
        """发送服务启停通知。

        Args:
            action: BanAction.START 或 BanAction.STOP
            jail: jail 名称

        Returns:
            True 表示消息已处理。
        """
        ncfg = self._config.notify

        if not ncfg.enable_service_alert:
            logger.debug("服务通知已关闭，跳过 action=%s", action.value)
            return True

        now = _format_time()

        if action == BanAction.START:
            message = SERVICE_START_TEMPLATE.format(
                jail=jail or "all",
                time=now,
            )
        elif action == BanAction.STOP:
            message = SERVICE_STOP_TEMPLATE.format(
                jail=jail or "all",
                time=now,
            )
        else:
            logger.warning("不支持的服务通知类型: %s", action.value)
            return False

        await self._send_message(message)
        logger.info("已发送服务通知: action=%s jail=%s",
                     action.value, jail)
        return True

    # ── 内部方法 ──────────────────────────────

    def _build_message(self, event: BanEvent, geo_info: GeoInfo) -> str:
        """根据事件类型构造对应的 HTML 消息文本。"""
        now = _format_time(event.timestamp)

        country_display = geo_info.country or "未知"
        flag_display = geo_info.flag or ""

        if event.action == BanAction.BAN:
            # 统计当前封禁总数
            total_banned = self._count_current_bans()

            return BAN_TEMPLATE.format(
                jail=event.jail,
                ip=event.ip,
                country=country_display,
                flag=flag_display,
                failures=event.failures,
                time=now,
                matches_preview=_truncate_matches(event.matches),
                total_banned=total_banned,
            )
        else:
            # UNBAN
            return UNBAN_TEMPLATE.format(
                ip=event.ip,
                jail=event.jail,
                time=now,
                ban_duration=_estimate_ban_duration(event),
            )

    async def _send_message(self, message: str) -> bool:
        """通过 bot 发送消息。

        bot 为 None 时不崩溃，只记录日志。
        """
        if self._bot is None:
            logger.debug("bot 未配置，跳过发送消息")
            return False

        try:
            chat_id = self._config.telegram.notify_chat_id
            if chat_id == 0:
                logger.warning("notify_chat_id 未设置，无法发送消息")
                return False

            return await self._bot.send_alert(
                chat_id=chat_id,
                message=message,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("发送消息失败: %s", e)
            return False

    def _record_event(self, event: BanEvent, geo_info: GeoInfo) -> None:
        """记录事件到状态库。"""
        if self._db is None:
            logger.debug("db 未配置，跳过记录事件")
            return

        try:
            # 更新 country 字段
            if geo_info.country:
                event.country = geo_info.country
            elif geo_info.country_code:
                event.country = geo_info.country_code

            self._db.record_ban(event)
            logger.debug("已记录事件到状态库: ip=%s action=%s",
                         event.ip, event.action.value)
        except Exception as e:
            logger.error("记录事件到状态库失败: %s", e)

    def _count_current_bans(self) -> int:
        """统计当前封禁总数。"""
        if self._db is None:
            return 0

        try:
            bans = self._db.get_current_bans()
            return len(bans)
        except Exception as e:
            logger.debug("统计当前封禁数失败: %s", e)
            return 0

    def close(self) -> None:
        """清理资源。"""
        if self._geoip is not None:
            self._geoip.close()
