"""
f2b_manager.telegram_bot.keyboards
==================================

内联键盘组件。

主要用于危险操作的二次确认（如 /uninstall）。
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ── 回调数据常量 ──────────────────────────────

CALLBACK_CONFIRM = "uninstall_confirm"
CALLBACK_CANCEL = "uninstall_cancel"


def confirm_uninstall_keyboard() -> InlineKeyboardMarkup:
    """卸载确认键盘（确认 / 取消）"""
    keyboard = [
        [
            InlineKeyboardButton(
                "\u26a0\ufe0f 确认卸载", callback_data=CALLBACK_CONFIRM
            ),
            InlineKeyboardButton(
                "✖️ 取消", callback_data=CALLBACK_CANCEL
            ),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def confirm_keyboard(
    confirm_text: str = "确认",
    cancel_text: str = "取消",
    confirm_callback: str = "confirm",
    cancel_callback: str = "cancel",
) -> InlineKeyboardMarkup:
    """通用确认键盘"""
    keyboard = [
        [
            InlineKeyboardButton(
                confirm_text, callback_data=confirm_callback
            ),
            InlineKeyboardButton(
                cancel_text, callback_data=cancel_callback
            ),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)
