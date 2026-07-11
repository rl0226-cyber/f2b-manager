"""
tests/test_notify.py
====================
预警消息构造与发送测试。

覆盖: 封禁消息构造 / 解封消息构造 / 服务通知消息 / bot mock 发送 /
       去重集成 / 通知开关 / GeoIP 查询 mock。

注意: AlertSender 在 __init__ 中延迟导入 GeoIPLookup 和 DedupTracker，
     因此 mock 目标为 f2b_manager.notify.geoip.GeoIPLookup 和
     f2b_manager.notify.dedup.DedupTracker。
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from f2b_manager.notify.sender import (
    AlertSender,
    _format_time,
    _truncate_matches,
    _estimate_ban_duration,
    BAN_TEMPLATE,
    UNBAN_TEMPLATE,
    SERVICE_START_TEMPLATE,
    SERVICE_STOP_TEMPLATE,
)
from f2b_manager.storage.models import BanAction, BanEvent, GeoInfo


# ── 统一的 mock 上下文管理器 ──────────────────

def mock_geoip_and_dedup(geo_return=None, dedup_should_send=True):
    """返回一个复合上下文管理器，mock GeoIPLookup 和 DedupTracker。

    可指定:
    - geo_return: GeoIPLookup.lookup 的返回值 (GeoInfo 实例)
    - dedup_should_send: DedupTracker.should_send 的返回值 (bool 或 list)
    """
    geo = MagicMock()
    geo.lookup = AsyncMock(return_value=geo_return or GeoInfo())
    geo_ctx = patch(
        "f2b_manager.notify.geoip.GeoIPLookup",
        return_value=geo,
    )

    dedup = MagicMock()
    dedup.should_send.return_value = dedup_should_send
    dedup_ctx = patch(
        "f2b_manager.notify.dedup.DedupTracker",
        return_value=dedup,
    )

    return geo_ctx, dedup_ctx, geo, dedup


# ── 测试类 ────────────────────────────────────

class TestMessageHelpers:
    """消息构造工具函数测试"""

    def test_format_time(self):
        dt = datetime(2026, 7, 11, 14, 30, 0)
        assert _format_time(dt) == "2026-07-11 14:30:00"

    def test_format_time_default(self):
        result = _format_time()
        assert result
        assert len(result) == 19  # YYYY-MM-DD HH:MM:SS

    def test_truncate_matches_short(self):
        result = _truncate_matches("short log", max_length=200)
        assert result == "short log"

    def test_truncate_matches_long(self):
        long_text = "x" * 300
        result = _truncate_matches(long_text, max_length=200)
        # 200 chars + "...(已截断)" = 208 chars
        assert len(result) == 208
        assert "(已截断)" in result

    def test_truncate_matches_empty(self):
        assert _truncate_matches("") == "(无)"

    def test_estimate_ban_duration(self):
        event = BanEvent(
            ip="1.2.3.4", jail="sshd",
            action=BanAction.UNBAN, timestamp=datetime.now(),
        )
        assert _estimate_ban_duration(event) == "未知"


class TestMessageTemplates:
    """消息模板格式测试"""

    def test_ban_template_format(self):
        msg = BAN_TEMPLATE.format(
            jail="sshd",
            ip="1.2.3.4",
            country="美国",
            flag="US",
            failures=5,
            time="2026-07-11 14:30:00",
            matches_preview="test match",
            total_banned=10,
        )
        assert "IP 封禁预警" in msg
        assert "sshd" in msg
        assert "1.2.3.4" in msg
        assert "美国" in msg
        assert "5" in msg
        assert "10" in msg

    def test_unban_template_format(self):
        msg = UNBAN_TEMPLATE.format(
            ip="1.2.3.4",
            jail="sshd",
            time="2026-07-11 15:00:00",
            ban_duration="30 分钟",
        )
        assert "IP 已解封" in msg
        assert "1.2.3.4" in msg

    def test_service_start_template(self):
        msg = SERVICE_START_TEMPLATE.format(jail="sshd", time="2026-07-11 08:00:00")
        assert "Fail2ban 服务启动" in msg

    def test_service_stop_template(self):
        msg = SERVICE_STOP_TEMPLATE.format(jail="all", time="2026-07-11 20:00:00")
        assert "Fail2ban 服务停止" in msg


class TestAlertSenderConstruction:
    """AlertSender 构造测试"""

    def test_create_without_bot_and_db(self, sample_config):
        geo_ctx, dedup_ctx, _, _ = mock_geoip_and_dedup()
        with geo_ctx, dedup_ctx:
            sender = AlertSender(config=sample_config, bot=None, db=None)
            assert sender is not None

    def test_create_with_mock_bot(self, sample_config, mock_bot):
        geo_ctx, dedup_ctx, _, _ = mock_geoip_and_dedup()
        with geo_ctx, dedup_ctx:
            sender = AlertSender(config=sample_config, bot=mock_bot, db=None)
            assert sender is not None


class TestBuildMessage:
    """消息构造方法测试"""

    @pytest.fixture
    def sender(self, sample_config):
        geo_ctx, dedup_ctx, _, _ = mock_geoip_and_dedup()
        with geo_ctx, dedup_ctx:
            s = AlertSender(config=sample_config, bot=None, db=None)
            yield s

    def test_build_ban_message(self, sender, sample_ban_event):
        geo = GeoInfo(country="美国", flag="US")
        msg = sender._build_message(sample_ban_event, geo)
        assert "IP 封禁预警" in msg
        assert "203.0.113.1" in msg
        assert "美国" in msg
        assert "sshd" in msg

    def test_build_unban_message(self, sender, sample_unban_event):
        geo = GeoInfo()
        msg = sender._build_message(sample_unban_event, geo)
        assert "IP 已解封" in msg
        assert "203.0.113.1" in msg
        assert "sshd" in msg

    def test_build_ban_without_geo(self, sender, sample_ban_event):
        geo = GeoInfo()
        msg = sender._build_message(sample_ban_event, geo)
        assert "未知" in msg

    def test_build_ban_matches_truncation(self, sender, sample_ban_event):
        sample_ban_event.matches = "x" * 300
        geo = GeoInfo()
        msg = sender._build_message(sample_ban_event, geo)
        assert "(已截断)" in msg


class TestSendAlert:
    """预警发送完整流程测试"""

    @pytest.fixture
    def sender_with_bot(self, sample_config, mock_bot, tmp_db):
        geo_ctx, dedup_ctx, geo, dedup = mock_geoip_and_dedup(
            geo_return=GeoInfo(country="美国", flag="US"),
        )
        with geo_ctx, dedup_ctx:
            s = AlertSender(config=sample_config, bot=mock_bot, db=tmp_db)
            yield s, geo, dedup

    @pytest.fixture
    def sender_without_bot(self, sample_config, tmp_db):
        geo_ctx, dedup_ctx, geo, dedup = mock_geoip_and_dedup(
            geo_return=GeoInfo(country="美国", flag="US"),
        )
        with geo_ctx, dedup_ctx:
            s = AlertSender(config=sample_config, bot=None, db=tmp_db)
            yield s

    @pytest.mark.asyncio
    async def test_send_ban_alert_with_bot(self, sender_with_bot, sample_ban_event, mock_bot):
        sender, _, _ = sender_with_bot
        result = await sender.send_ban_alert(sample_ban_event)
        assert result is True
        assert len(mock_bot.alerts) >= 1
        alert = mock_bot.alerts[0]
        assert "IP 封禁预警" in alert["message"]
        assert alert["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_send_ban_alert_records_to_db(self, sender_with_bot, sample_ban_event, tmp_db):
        sender, _, _ = sender_with_bot
        await sender.send_ban_alert(sample_ban_event)
        history = tmp_db.get_ban_history(days=7)
        assert len(history) >= 1
        assert history[0].ip == sample_ban_event.ip

    @pytest.mark.asyncio
    async def test_send_ban_alert_without_bot(self, sender_without_bot, sample_ban_event):
        result = await sender_without_bot.send_ban_alert(sample_ban_event)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_unban_alert_skip_if_disabled(self, sample_config, sample_unban_event, tmp_db):
        sample_config.notify.enable_unban_alert = False
        mock_bot_local = MagicMock()
        mock_bot_local.send_alert = AsyncMock()

        geo_ctx, dedup_ctx, _, _ = mock_geoip_and_dedup()
        with geo_ctx, dedup_ctx:
            sender = AlertSender(config=sample_config, bot=mock_bot_local, db=tmp_db)
            await sender.send_ban_alert(sample_unban_event)
            mock_bot_local.send_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_ban_alert_dedup_blocks(self, sample_config, sample_ban_event, tmp_db):
        mock_bot_local = MagicMock()
        mock_bot_local.send_alert = AsyncMock()

        geo_ctx, dedup_ctx, _, dedup = mock_geoip_and_dedup()
        dedup.should_send.side_effect = [True, False]

        with geo_ctx, dedup_ctx:
            sender = AlertSender(config=sample_config, bot=mock_bot_local, db=tmp_db)
            await sender.send_ban_alert(sample_ban_event)
            await sender.send_ban_alert(sample_ban_event)
            assert mock_bot_local.send_alert.call_count == 1

    @pytest.mark.asyncio
    async def test_send_ban_alert_bot_failure(self, sample_config, sample_ban_event, mock_bot, tmp_db):
        mock_bot.should_fail = True

        geo_ctx, dedup_ctx, _, _ = mock_geoip_and_dedup()
        with geo_ctx, dedup_ctx:
            sender = AlertSender(config=sample_config, bot=mock_bot, db=tmp_db)
            result = await sender.send_ban_alert(sample_ban_event)
            assert result is True


class TestServiceAlert:
    """服务通知测试"""

    @pytest.fixture
    def sender(self, sample_config, mock_bot):
        geo_ctx, dedup_ctx, _, _ = mock_geoip_and_dedup()
        with geo_ctx, dedup_ctx:
            s = AlertSender(config=sample_config, bot=mock_bot, db=None)
            yield s

    @pytest.mark.asyncio
    async def test_send_service_start(self, sender, mock_bot):
        result = await sender.send_service_alert(BanAction.START, jail="sshd")
        assert result is True
        assert len(mock_bot.alerts) == 1
        assert "服务启动" in mock_bot.alerts[0]["message"]

    @pytest.mark.asyncio
    async def test_send_service_stop(self, sender, mock_bot):
        result = await sender.send_service_alert(BanAction.STOP, jail="sshd")
        assert result is True
        assert len(mock_bot.alerts) == 1
        assert "服务停止" in mock_bot.alerts[0]["message"]

    @pytest.mark.asyncio
    async def test_send_service_alert_disabled(self, sample_config, mock_bot):
        sample_config.notify.enable_service_alert = False
        geo_ctx, dedup_ctx, _, _ = mock_geoip_and_dedup()
        with geo_ctx, dedup_ctx:
            sender = AlertSender(config=sample_config, bot=mock_bot, db=None)
            result = await sender.send_service_alert(BanAction.START, jail="sshd")
            assert result is True
            assert len(mock_bot.alerts) == 0

    @pytest.mark.asyncio
    async def test_send_service_alert_invalid_action(self, sender):
        result = await sender.send_service_alert(BanAction.BAN, jail="sshd")
        assert result is False

    @pytest.mark.asyncio
    async def test_service_alert_without_bot(self, sample_config):
        sample_config.notify.enable_service_alert = True
        geo_ctx, dedup_ctx, _, _ = mock_geoip_and_dedup()
        with geo_ctx, dedup_ctx:
            sender = AlertSender(config=sample_config, bot=None, db=None)
            result = await sender.send_service_alert(BanAction.START)
            assert result is True

    @pytest.mark.asyncio
    async def test_service_alert_empty_jail_defaults(self, sender, mock_bot):
        await sender.send_service_alert(BanAction.START, jail="")
        assert len(mock_bot.alerts) == 1
        assert "all" in mock_bot.alerts[0]["message"]


class TestAlertSenderClose:
    """资源清理测试"""

    def test_close_with_geoip(self, sample_config):
        with patch("f2b_manager.notify.geoip.GeoIPLookup") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            with patch("f2b_manager.notify.dedup.DedupTracker"):
                sender = AlertSender(config=sample_config, bot=None, db=None)
                sender.close()
                mock_instance.close.assert_called_once()

    def test_close_without_geoip(self, sample_config):
        geo_ctx, dedup_ctx, _, _ = mock_geoip_and_dedup()
        with geo_ctx, dedup_ctx:
            sender = AlertSender(config=sample_config, bot=None, db=None)
            sender._geoip = None
            sender.close()
