"""
f2b_manager.telegram_bot.handlers.manage
==========================================

安装管理命令 handler。

命令:
    /install    — 安装 Fail2ban（异步执行 + 进度推送）
    /uninstall  — 卸载 Fail2ban（ConversationHandler 二次确认）
    /update     — 更新 Fail2ban（异步执行 + 进度推送）
    /reload     — 重载 Fail2ban 配置

权限: 管理员 (ADMIN)

ConversationHandler 状态机 (/uninstall):
    /uninstall → CONFIRM → [确认按钮] → 执行卸载 → END
                        → [取消按钮] → END
                        → /cancel     → END
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, \
    ContextTypes, ConversationHandler

from ..auth import require_admin
from ..deps import get_deps
from ..formatters import esc, format_cancelled, format_error, \
    format_install_result, format_not_ready, format_progress, format_success
from ..keyboards import CALLBACK_CANCEL, CALLBACK_CONFIRM, \
    confirm_uninstall_keyboard

logger = logging.getLogger(__name__)

# ConversationHandler 状态
CONFIRM = 1


# ──────────────────────────────────────────────
# 长耗时操作辅助
# ──────────────────────────────────────────────

async def _run_with_progress(
    message: Any,
    operation: Callable,
    initial_text: str,
    steps: list[str],
    action_label: str,
) -> str:
    """在 executor 中执行同步操作，期间推送进度消息。

    Args:
        message: 可 edit_text 的消息对象 (Message)
        operation: 同步可调用对象
        initial_text: 初始进度消息
        steps: 进度步骤文案列表
        action_label: 操作标签（用于日志）

    Returns:
        最终结果文本（已格式化），若异常则返回错误文本
    """
    loop = asyncio.get_running_loop()

    # 发送初始进度（若与已有内容相同则忽略）
    try:
        await message.edit_text(
            format_progress(initial_text), parse_mode="HTML"
        )
    except Exception:
        pass  # 内容未变时 Telegram 返回 400，忽略即可

    # 提交到线程池
    task = loop.run_in_executor(None, operation)

    # 轮询进度
    step_idx = 0
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=4.0)
        except asyncio.TimeoutError:
            # 仍在运行，推送下一步进度
            if step_idx < len(steps):
                try:
                    await message.edit_text(
                        format_progress(steps[step_idx]), parse_mode="HTML"
                    )
                except Exception:
                    pass  # 编辑失败（频率限制等）不影响执行
                step_idx += 1
            else:
                # 步骤用完，显示通用进度
                elapsed = step_idx * 4
                try:
                    await message.edit_text(
                        format_progress(
                            f"正在{action_label}... 已耗时 {elapsed}s"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                step_idx += 1

    # 获取结果
    try:
        result = task.result()
        return format_install_result(result, action_label)
    except Exception as e:
        logger.exception(f"{action_label}操作异常")
        return format_error(f"{action_label}失败: {e}")


# ──────────────────────────────────────────────
# /install
# ──────────────────────────────────────────────

@require_admin
async def cmd_install(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/install — 安装 Fail2ban"""
    deps = get_deps(context)
    installer = deps.get_installer()

    if installer is None:
        await update.message.reply_text(format_not_ready(), parse_mode="HTML")
        return

    # 发送进度消息（使用 reply_text 创建新消息，后续 edit_text 更新）
    progress_msg = await update.message.reply_text(
        format_progress("正在安装 Fail2ban，请稍候..."), parse_mode="HTML"
    )

    steps = [
        "正在检测系统发行版...",
        "正在更新包索引...",
        "正在安装依赖包...",
        "正在安装 Fail2ban...",
        "正在生成 jail.local 配置...",
        "正在部署 Telegram 通知 action...",
        "正在部署 notify.sh 脚本...",
        "正在启动并启用 fail2ban 服务...",
        "正在验证安装...",
    ]

    result_text = await _run_with_progress(
        message=progress_msg,
        operation=installer.install,
        initial_text="正在安装 Fail2ban，请稍候...",
        steps=steps,
        action_label="安装",
    )

    await progress_msg.edit_text(result_text, parse_mode="HTML")
    logger.info(
        f"安装操作完成 (chat_id={update.effective_chat.id})"
    )


# ──────────────────────────────────────────────
# /update
# ──────────────────────────────────────────────

@require_admin
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/update — 更新 Fail2ban"""
    deps = get_deps(context)
    installer = deps.get_installer()

    if installer is None:
        await update.message.reply_text(format_not_ready(), parse_mode="HTML")
        return

    progress_msg = await update.message.reply_text(
        format_progress("正在更新 Fail2ban，请稍候..."), parse_mode="HTML"
    )

    steps = [
        "正在检测当前版本...",
        "正在更新包索引...",
        "正在升级 Fail2ban...",
        "正在重启 fail2ban 服务...",
        "正在验证更新结果...",
    ]

    result_text = await _run_with_progress(
        message=progress_msg,
        operation=installer.update,
        initial_text="正在更新 Fail2ban，请稍候...",
        steps=steps,
        action_label="更新",
    )

    await progress_msg.edit_text(result_text, parse_mode="HTML")
    logger.info(
        f"更新操作完成 (chat_id={update.effective_chat.id})"
    )


# ──────────────────────────────────────────────
# /reload
# ──────────────────────────────────────────────

@require_admin
async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reload — 重载 Fail2ban 配置"""
    deps = get_deps(context)

    if deps.f2b_manager is None:
        await update.message.reply_text(format_not_ready(), parse_mode="HTML")
        return

    try:
        success = deps.f2b_manager.reload()
        if success:
            await update.message.reply_text(
                format_success("Fail2ban 配置已重载"), parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                format_error("重载失败，fail2ban-client reload 返回非零状态"),
                parse_mode="HTML",
            )
    except Exception as e:
        logger.exception("重载失败")
        await update.message.reply_text(
            format_error(f"重载失败: {e}"), parse_mode="HTML"
        )


# ──────────────────────────────────────────────
# /uninstall — ConversationHandler
# ──────────────────────────────────────────────

@require_admin
async def cmd_uninstall_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/uninstall 入口 — 显示二次确认键盘"""
    deps = get_deps(context)
    installer = deps.get_installer()

    if installer is None:
        await update.message.reply_text(format_not_ready(), parse_mode="HTML")
        return ConversationHandler.END

    # 保存 installer 引用，供 callback 使用
    context.user_data["uninstall_chat_id"] = update.effective_chat.id

    await update.message.reply_text(
        "\u26a0\ufe0f <b>确认卸载 Fail2ban</b>\n\n"
        "此操作将执行以下步骤：\n"
        "  • 停止 fail2ban 服务\n"
        "  • 禁用开机自启\n"
        "  • 卸载 fail2ban 软件包\n"
        "  • 备份配置文件到 /etc/fail2ban.backup\n"
        "  • 清理通知脚本\n\n"
        "<b>此操作不可逆！确认继续？</b>",
        reply_markup=confirm_uninstall_keyboard(),
        parse_mode="HTML",
    )
    return CONFIRM


async def uninstall_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """卸载确认回调 — 处理确认/取消按钮"""
    query = update.callback_query
    await query.answer()

    deps = get_deps(context)

    # ── 取消 ──
    if query.data == CALLBACK_CANCEL:
        await query.edit_message_text(
            format_cancelled(), parse_mode="HTML"
        )
        return ConversationHandler.END

    # ── 确认 ──
    if query.data == CALLBACK_CONFIRM:
        installer = deps.get_installer()
        if installer is None:
            await query.edit_message_text(
                format_not_ready(), parse_mode="HTML"
            )
            return ConversationHandler.END

        # 发送进度消息
        await query.edit_message_text(
            format_progress("正在卸载 Fail2ban，请稍候..."),
            parse_mode="HTML",
        )

        loop = asyncio.get_running_loop()

        # 在 executor 中执行卸载（保留配置备份）
        uninstall_op = functools.partial(
            installer.uninstall, keep_config=True
        )

        try:
            result = await loop.run_in_executor(None, uninstall_op)
            await query.edit_message_text(
                format_install_result(result, "卸载"),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception("卸载操作异常")
            await query.edit_message_text(
                format_error(f"卸载失败: {e}"), parse_mode="HTML"
            )

        logger.info(
            f"卸载操作完成 (chat_id={update.effective_chat.id})"
        )
        return ConversationHandler.END

    # 未知回调
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/cancel — 取消当前操作（ConversationHandler fallback）"""
    await update.message.reply_text(
        format_cancelled(), parse_mode="HTML"
    )
    return ConversationHandler.END


# ──────────────────────────────────────────────
# ConversationHandler 定义（供 bot.py 注册）
# ──────────────────────────────────────────────

def get_uninstall_handler() -> ConversationHandler:
    """创建 /uninstall 的 ConversationHandler"""
    return ConversationHandler(
        entry_points=[CommandHandler("uninstall", cmd_uninstall_entry)],
        states={
            CONFIRM: [
                CallbackQueryHandler(uninstall_callback),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
        ],
        # per_message=False（默认）:
        # 入口是 CommandHandler，states 含 CallbackQueryHandler
        # PTB 会发出信息性警告，这是正常的——对话流程正确
        per_user=True,
        per_chat=True,
    )
