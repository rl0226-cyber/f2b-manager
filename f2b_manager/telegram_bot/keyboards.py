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


# ── 定时报告设置键盘 ──────────────────────────

# 回调数据前缀
CB_SCHEDULE = "sch"

# 预设时间列表
PRESET_TIMES = ["06:00", "08:00", "10:00", "12:00", "18:00", "20:00", "22:00"]

# 星期映射
WEEKDAY_MAP = [
    ("monday", "周一"),
    ("tuesday", "周二"),
    ("wednesday", "周三"),
    ("thursday", "周四"),
    ("friday", "周五"),
    ("saturday", "周六"),
    ("sunday", "周日"),
]


def schedule_main_keyboard(
    daily_enabled: bool,
    daily_time: str,
    weekly_enabled: bool,
    weekly_day: str,
    weekly_time: str,
) -> InlineKeyboardMarkup:
    """定时报告主设置面板"""
    daily_label = f"{'🟢' if daily_enabled else '🔴'} 每日报告: {daily_time}"
    weekly_label = f"{'🟢' if weekly_enabled else '🔴'} 每周报告: {weekly_day} {weekly_time}"

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ 开启每日" if not daily_enabled else "❌ 关闭每日",
                callback_data=f"{CB_SCHEDULE}_tog_d",
            ),
            InlineKeyboardButton(
                "🕐 每日时间", callback_data=f"{CB_SCHEDULE}_timed"
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ 开启每周" if not weekly_enabled else "❌ 关闭每周",
                callback_data=f"{CB_SCHEDULE}_tog_w",
            ),
            InlineKeyboardButton(
                "🕐 每周时间", callback_data=f"{CB_SCHEDULE}_timew"
            ),
            InlineKeyboardButton(
                "📅 每周星期", callback_data=f"{CB_SCHEDULE}_dayw"
            ),
        ],
        [
            InlineKeyboardButton(
                "✖ 关闭菜单", callback_data=f"{CB_SCHEDULE}_del"
            ),
        ],
    ]
    # 状态说明行（不可点击）
    status_line = f"{'🟢' if daily_enabled else '🔴'} 每日: {daily_time} ｜ "
    status_line += f"{'🟢' if weekly_enabled else '🔴'} 每周: {weekly_day} {weekly_time}"

    return InlineKeyboardMarkup(keyboard)


def schedule_time_keyboard(target: str) -> InlineKeyboardMarkup:
    """预设时间选择键盘

    Args:
        target: 'daily' 或 'weekly'，区分设置目标
    """
    keyboard = []
    row = []
    for t in PRESET_TIMES:
        row.append(
            InlineKeyboardButton(t, callback_data=f"{CB_SCHEDULE}_tm_{target}:{t}")
        )
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("↩ 返回", callback_data=f"{CB_SCHEDULE}_main"),
        InlineKeyboardButton("✖ 关闭", callback_data=f"{CB_SCHEDULE}_del"),
    ])
    return InlineKeyboardMarkup(keyboard)


def schedule_weekday_keyboard(current_day: str = "monday") -> InlineKeyboardMarkup:
    """星期选择键盘

    Args:
        current_day: 当前设置的星期，用于高亮
    """
    keyboard = []
    row = []
    for eng, chn in WEEKDAY_MAP:
        label = f"● {chn}" if eng == current_day else chn
        row.append(
            InlineKeyboardButton(label, callback_data=f"{CB_SCHEDULE}_dy_{eng}")
        )
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("↩ 返回", callback_data=f"{CB_SCHEDULE}_main"),
        InlineKeyboardButton("✖ 关闭", callback_data=f"{CB_SCHEDULE}_del"),
    ])
    return InlineKeyboardMarkup(keyboard)
