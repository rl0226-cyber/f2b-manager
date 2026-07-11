"""
f2b_manager.telegram_bot.auth
=============================

三级权限鉴权。

权限模型:
    ADMIN (3)    — 全部操作：安装/卸载/更新/封禁/配置
    OPERATOR (2) — 状态查询 + 报告 + 通知开关
    VIEWER (1)   — 仅 /start /help

权限通过 config.telegram.admin_chat_ids 和 operator_chat_ids 判断。
提供 require_admin / require_operator 装饰器给 handler 使用。
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Callable, Optional

from ..storage.models import AuthLevel

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

    from ..config import TelegramConfig

logger = logging.getLogger(__name__)


class AuthManager:
    """三级权限管理器

    根据 chat_id 判断用户权限等级。
    admin_chat_ids → ADMIN, operator_chat_ids → OPERATOR, 其余 → VIEWER。
    """

    def __init__(self, tg_config: Optional["TelegramConfig"] = None):
        self._admin_ids: set[int] = set()
        self._operator_ids: set[int] = set()

        if tg_config is not None:
            self._admin_ids = set(tg_config.admin_chat_ids)
            self._operator_ids = set(tg_config.operator_chat_ids)

    def get_level(self, chat_id: int) -> AuthLevel:
        """获取 chat_id 对应的权限等级"""
        if chat_id in self._admin_ids:
            return AuthLevel.ADMIN
        if chat_id in self._operator_ids:
            return AuthLevel.OPERATOR
        return AuthLevel.VIEWER

    def authorize(self, chat_id: int, required: AuthLevel) -> bool:
        """检查 chat_id 是否拥有足够权限"""
        return self.get_level(chat_id) >= required

    def is_admin(self, chat_id: int) -> bool:
        return self.get_level(chat_id) >= AuthLevel.ADMIN

    def is_operator(self, chat_id: int) -> bool:
        return self.get_level(chat_id) >= AuthLevel.OPERATOR

    def level_name(self, chat_id: int) -> str:
        """返回权限等级中文名"""
        level = self.get_level(chat_id)
        names = {
            AuthLevel.ADMIN: "管理员",
            AuthLevel.OPERATOR: "操作员",
            AuthLevel.VIEWER: "访客",
        }
        return names.get(level, "未知")


# ──────────────────────────────────────────────
# 装饰器
# ──────────────────────────────────────────────

# 延迟导入，避免循环
def _get_auth(context: "ContextTypes.DEFAULT_TYPE") -> Optional[AuthManager]:
    """从 context.bot_data 获取 AuthManager"""
    deps = context.bot_data.get("deps")
    if deps is not None:
        return deps.auth
    return context.bot_data.get("auth")


def _deny_message(required: AuthLevel) -> str:
    """构造拒绝消息"""
    level_name = {AuthLevel.ADMIN: "管理员", AuthLevel.OPERATOR: "操作员"}
    name = level_name.get(required, "授权")
    return f"\u26d4\ufe0f <b>权限不足</b>\n\n此命令需要 <b>{name}</b> 权限。\n你的权限等级不足以执行此操作。"


def require_admin(func: Callable) -> Callable:
    """装饰器：仅允许 ADMIN 执行

    未授权时发送拒绝消息并返回 None（不继续执行 / 不进入对话状态）。
    """

    @functools.wraps(func)
    async def wrapper(
        update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ):
        chat = update.effective_chat
        if chat is None:
            return None

        auth = _get_auth(context)
        if auth is None or not auth.is_admin(chat.id):
            logger.warning(f"未授权访问 (admin): chat_id={chat.id}")
            msg = update.effective_message or update.callback_query
            if msg is not None:
                if hasattr(msg, "reply_text"):
                    await msg.reply_text(
                        _deny_message(AuthLevel.ADMIN), parse_mode="HTML"
                    )
                elif hasattr(msg, "answer"):
                    await msg.answer(
                        _deny_message(AuthLevel.ADMIN), parse_mode="HTML"
                    )
            return None

        return await func(update, context)

    return wrapper


def require_operator(func: Callable) -> Callable:
    """装饰器：允许 OPERATOR 及以上执行"""

    @functools.wraps(func)
    async def wrapper(
        update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ):
        chat = update.effective_chat
        if chat is None:
            return None

        auth = _get_auth(context)
        if auth is None or not auth.is_operator(chat.id):
            logger.warning(f"未授权访问 (operator): chat_id={chat.id}")
            msg = update.effective_message or update.callback_query
            if msg is not None:
                if hasattr(msg, "reply_text"):
                    await msg.reply_text(
                        _deny_message(AuthLevel.OPERATOR), parse_mode="HTML"
                    )
                elif hasattr(msg, "answer"):
                    await msg.answer(
                        _deny_message(AuthLevel.OPERATOR), parse_mode="HTML"
                    )
            return None

        return await func(update, context)

    return wrapper
