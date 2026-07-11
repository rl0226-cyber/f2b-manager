"""
tests/test_cli.py
=================
CLI notify 命令测试。

覆盖:
- bot_token 存在时，_cmd_notify 构造 _CliBotSender 并正确调用 send_alert
- bot_token 不存在时，_cmd_notify 不报错，AlertSender 收到 bot=None
- _CliBotSender.send_alert 实际调用 telegram.Bot.send_message
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from f2b_manager.config import AppConfig, TelegramConfig


# ── helpers ────────────────────────────────────

def _make_args(**kwargs):
    """构造类似 argparse.Namespace 的 mock args 对象。"""
    args = MagicMock()
    args.event = kwargs.get("event", "ban")
    args.ip = kwargs.get("ip", "203.0.113.1")
    args.jail = kwargs.get("jail", "sshd")
    args.failures = kwargs.get("failures", "5")
    args.matches = kwargs.get("matches", "test log line")
    return args


def _make_config(*, bot_token: str = "", notify_chat_id: int = 0):
    """构造测试用 AppConfig。"""
    return AppConfig(
        telegram=TelegramConfig(
            bot_token=bot_token,
            admin_chat_ids=[123456789],
            notify_chat_id=notify_chat_id,
        ),
    )


# ── Test: _CliBotSender ────────────────────────

class TestCliBotSender:
    """_CliBotSender 单元测试。

    _CliBotSender.__init__ 内部 import telegram.Bot，因此
    需要 patch telegram.Bot 而非 f2b_manager.cli.Bot。
    """

    @pytest.mark.asyncio
    async def test_send_alert_calls_bot_send_message(self):
        """send_alert 应该调用 telegram.Bot.send_message。"""
        from f2b_manager.cli import _CliBotSender

        with patch("telegram.Bot") as MockBot:
            mock_bot_instance = MockBot.return_value
            mock_bot_instance.send_message = AsyncMock(return_value=None)

            sender = _CliBotSender(token="test:token123")
            result = await sender.send_alert(
                chat_id=12345,
                message="<b>Test Alert</b>",
                parse_mode="HTML",
            )

            assert result is True
            mock_bot_instance.send_message.assert_called_once_with(
                chat_id=12345,
                text="<b>Test Alert</b>",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

    @pytest.mark.asyncio
    async def test_send_alert_handles_forbidden(self):
        """Forbidden 异常应返回 False，不抛出。"""
        from f2b_manager.cli import _CliBotSender
        from telegram.error import Forbidden

        with patch("telegram.Bot") as MockBot:
            mock_bot_instance = MockBot.return_value
            mock_bot_instance.send_message = AsyncMock(
                side_effect=Forbidden("blocked")
            )

            sender = _CliBotSender(token="test:token123")
            result = await sender.send_alert(chat_id=12345, message="test")

            assert result is False

    @pytest.mark.asyncio
    async def test_send_alert_handles_network_error(self):
        """NetworkError 异常应返回 False。"""
        from f2b_manager.cli import _CliBotSender
        from telegram.error import NetworkError

        with patch("telegram.Bot") as MockBot:
            mock_bot_instance = MockBot.return_value
            mock_bot_instance.send_message = AsyncMock(
                side_effect=NetworkError("timeout")
            )

            sender = _CliBotSender(token="test:token123")
            result = await sender.send_alert(chat_id=12345, message="test")

            assert result is False

    @pytest.mark.asyncio
    async def test_send_alert_handles_generic_telegram_error(self):
        """通用 TelegramError 异常应返回 False。"""
        from f2b_manager.cli import _CliBotSender
        from telegram.error import TelegramError

        with patch("telegram.Bot") as MockBot:
            mock_bot_instance = MockBot.return_value
            mock_bot_instance.send_message = AsyncMock(
                side_effect=TelegramError("unknown error")
            )

            sender = _CliBotSender(token="test:token123")
            result = await sender.send_alert(chat_id=12345, message="test")

            assert result is False

    @pytest.mark.asyncio
    async def test_send_report_returns_false(self):
        """CLI 模式下 send_report 应返回 False（不支持）。"""
        from f2b_manager.cli import _CliBotSender

        with patch("telegram.Bot") as MockBot:
            sender = _CliBotSender(token="test:token123")
            result = await sender.send_report(chat_id=12345, message="report")
            assert result is False


# ── Test: _cmd_notify integration ──────────────

class TestCmdNotifyWithToken:
    """bot_token 存在时的 _cmd_notify 集成测试。

    _cmd_notify 内部 import StateDB、AlertSender 等，需在目标模块处 patch。
    """

    def test_creates_cli_bot_sender_when_token_present(self):
        """有 bot_token 时 AlertSender 应收到非 None 的 bot。"""
        from f2b_manager.cli import _cmd_notify

        config = _make_config(bot_token="real:token123", notify_chat_id=12345)
        args = _make_args()

        with patch("f2b_manager.storage.database.StateDB") as MockStateDB, \
             patch("f2b_manager.notify.sender.AlertSender") as MockAlertSender, \
             patch("f2b_manager.cli._CliBotSender") as MockCliBotSender:

            mock_db = MockStateDB.return_value
            mock_db.close = MagicMock()

            mock_sender = MockAlertSender.return_value
            mock_sender.send_ban_alert = AsyncMock(return_value=True)
            mock_sender.close = MagicMock()

            mock_bot = MockCliBotSender.return_value

            result = _cmd_notify(config, args)

            # 验证 _CliBotSender 被创建
            MockCliBotSender.assert_called_once_with("real:token123")

            # 验证 AlertSender 被创建时 bot 参数不为 None
            _, call_kwargs = MockAlertSender.call_args
            assert call_kwargs["bot"] is mock_bot

            # 验证 send_ban_alert 被调用
            mock_sender.send_ban_alert.assert_called_once()

            # 验证返回码为 0（成功）
            assert result == 0


class TestCmdNotifyWithoutToken:
    """bot_token 不存在时的 _cmd_notify 集成测试"""

    def test_alert_sender_receives_bot_none(self):
        """无 bot_token 时 AlertSender 应收到 bot=None，不报错。"""
        from f2b_manager.cli import _cmd_notify

        config = _make_config(bot_token="")
        args = _make_args()

        with patch("f2b_manager.storage.database.StateDB") as MockStateDB, \
             patch("f2b_manager.notify.sender.AlertSender") as MockAlertSender:

            mock_db = MockStateDB.return_value
            mock_db.close = MagicMock()

            mock_sender = MockAlertSender.return_value
            mock_sender.send_ban_alert = AsyncMock(return_value=True)
            mock_sender.close = MagicMock()

            result = _cmd_notify(config, args)

            # 验证 AlertSender 被创建时 bot=None
            _, call_kwargs = MockAlertSender.call_args
            assert call_kwargs["bot"] is None

            # 验证不报错，正常返回
            assert result == 0

    def test_no_token_no_crash(self):
        """无 bot_token 且数据库初始化失败时也应不报错。"""
        from f2b_manager.cli import _cmd_notify

        config = _make_config(bot_token="")
        args = _make_args()

        # 模拟 StateDB 初始化失败
        with patch("f2b_manager.storage.database.StateDB",
                   side_effect=Exception("disk full")), \
             patch("f2b_manager.notify.sender.AlertSender") as MockAlertSender:

            mock_sender = MockAlertSender.return_value
            mock_sender.send_ban_alert = AsyncMock(return_value=True)
            mock_sender.close = MagicMock()

            result = _cmd_notify(config, args)

            # 即使 db 失败，也应正常返回
            assert result == 0


class TestCmdNotifyUnbanEvent:
    """解封事件的 _cmd_notify 测试"""

    def test_unban_event_with_token(self):
        """UNBAN 事件有 token 时正常处理。"""
        from f2b_manager.cli import _cmd_notify

        config = _make_config(bot_token="test:token", notify_chat_id=12345)
        args = _make_args(event="unban")

        with patch("f2b_manager.storage.database.StateDB") as MockStateDB, \
             patch("f2b_manager.notify.sender.AlertSender") as MockAlertSender, \
             patch("f2b_manager.cli._CliBotSender"):

            mock_db = MockStateDB.return_value
            mock_db.close = MagicMock()

            mock_sender = MockAlertSender.return_value
            mock_sender.send_ban_alert = AsyncMock(return_value=True)
            mock_sender.close = MagicMock()

            result = _cmd_notify(config, args)
            assert result == 0
            mock_sender.send_ban_alert.assert_called_once()
