"""
f2b_manager.telegram_bot.bot
=============================

Telegram Bot 主类。

实现 IMessageSender 协议（send_alert / send_report），
注册全部 17 条命令的 handler，管理 Bot 生命周期。

构造函数接受 config、f2b_manager、db、installer，均可为 None（开发期 mock）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from telegram import Update
from telegram.error import Forbidden, NetworkError, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from ..config import AppConfig
from ..storage.database import StateDB
from ..storage.models import (
    AuthLevel,
    IFail2banInstaller,
    IFail2banManager,
    IMessageSender,
)
from ..utils.logger import get_logger
from .auth import AuthManager
from .deps import BotDeps
from .formatters import format_error, format_help, format_welcome
from .handlers.ban import cmd_ban, cmd_unban
from .handlers.config import cmd_setnotify, cmd_setschedule, cmd_whitelist, handle_schedule_callback, cmd_f2bconfig, handle_f2bconfig_callback
from .handlers.manage import (
    cmd_cancel,
    cmd_install,
    cmd_reload,
    cmd_update,
    get_uninstall_handler,
)
from .handlers.report import cmd_report, cmd_stats
from .handlers.status import cmd_banned, cmd_jail, cmd_jails, cmd_status

if TYPE_CHECKING:
    pass

logger = get_logger("telegram_bot")


class F2BTelegramBot(IMessageSender):
    """f2b-manager Telegram Bot

    功能:
        - 注册全部 17 条命令 handler
        - 三级权限鉴权（admin / operator / viewer）
        - /uninstall 二次确认（ConversationHandler）
        - /install /update 异步执行 + 进度推送
        - 实现 IMessageSender 协议（send_alert / send_report）

    生命周期:
        bot = F2BTelegramBot(config, f2b_manager, db, installer)
        await bot.run()       # 启动 polling/webhook
        await bot.shutdown()  # 关闭
    """

    def __init__(
        self,
        config: AppConfig,
        f2b_manager: Optional[IFail2banManager] = None,
        db: Optional[StateDB] = None,
        installer: Optional[IFail2banInstaller] = None,
    ) -> None:
        self.config = config
        self.f2b_manager = f2b_manager
        self.db = db
        self.installer = installer

        # 鉴权管理器
        self.auth = AuthManager(config.telegram)

        # 共享依赖
        self.deps = BotDeps(
            config=config,
            f2b_manager=f2b_manager,
            installer=installer,
            db=db,
            auth=self.auth,
        )

        # Application（延迟构建，开发期可能无 token）
        self._application: Optional[Application] = None
        self._initialized = False

        # 构建 Application（如果 token 存在）
        token = config.telegram.bot_token
        if token:
            self._application = (
                ApplicationBuilder()
                .token(token)
                .build()
            )
            self._register_handlers()
            self._register_deps()
            logger.info("Telegram Bot Application 已构建")
        else:
            logger.warning(
                "telegram.bot_token 未设置，Bot 将以 mock 模式运行"
                "（无法启动 polling，但 send_alert/send_report 可用于测试）"
            )

    # ──────────────────────────────────────────
    # Handler 注册
    # ──────────────────────────────────────────

    def _register_handlers(self) -> None:
        """注册全部命令 handler"""
        app = self._application
        if app is None:
            return

        # ── 基础命令（所有用户）──
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(CommandHandler("cancel", cmd_cancel))

        # ── 状态查询（操作员+）──
        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("jails", cmd_jails))
        app.add_handler(CommandHandler("banned", cmd_banned))
        app.add_handler(CommandHandler("jail", cmd_jail))

        # ── 封禁管理（管理员）──
        app.add_handler(CommandHandler("ban", cmd_ban))
        app.add_handler(CommandHandler("unban", cmd_unban))

        # ── 安装管理（管理员）──
        app.add_handler(CommandHandler("install", cmd_install))
        app.add_handler(CommandHandler("update", cmd_update))
        app.add_handler(CommandHandler("reload", cmd_reload))

        # /uninstall — ConversationHandler（二次确认）
        app.add_handler(get_uninstall_handler())

        # ── 报告统计（操作员+）──
        app.add_handler(CommandHandler("report", cmd_report))
        app.add_handler(CommandHandler("stats", cmd_stats))

        # ── 配置管理 ──
        app.add_handler(CommandHandler("whitelist", cmd_whitelist))
        app.add_handler(CommandHandler("setnotify", cmd_setnotify))
        app.add_handler(CommandHandler("setschedule", cmd_setschedule))
        app.add_handler(CommandHandler("f2bconfig", cmd_f2bconfig))

        # 回调处理器
        app.add_handler(CallbackQueryHandler(handle_schedule_callback, pattern=r"^sch_"))
        app.add_handler(CallbackQueryHandler(handle_f2bconfig_callback, pattern=r"^f2bcfg_"))

        # ── 全局错误处理 ──
        app.add_error_handler(self.error_handler)

        logger.info("已注册 18 条命令 handler")

    def _register_deps(self) -> None:
        """将 BotDeps 注入 Application.bot_data"""
        if self._application is not None:
            self._application.bot_data["deps"] = self.deps
            self._application.bot_data["auth"] = self.auth

    # ──────────────────────────────────────────
    # /start 和 /help（内置，不需要单独的 handler 文件）
    # ──────────────────────────────────────────

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/start — 欢迎信息 + 显示 chat_id"""
        chat = update.effective_chat
        if chat is None:
            return

        chat_id = chat.id
        level_name = self.auth.level_name(chat_id)

        await update.message.reply_text(
            format_welcome(chat_id, level_name),
            parse_mode="HTML",
        )

    async def _cmd_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/help — 命令帮助"""
        chat = update.effective_chat
        level_name = self.auth.level_name(chat.id) if chat else "访客"

        await update.message.reply_text(
            format_help(level_name),
            parse_mode="HTML",
        )

    # ──────────────────────────────────────────
    # IMessageSender 协议实现
    # ──────────────────────────────────────────

    async def send_alert(
        self,
        chat_id: int,
        message: str,
        parse_mode: str = "HTML",
    ) -> bool:
        """发送预警消息（供 notify 模块调用）

        实现 IMessageSender.send_alert。
        """
        if self._application is None:
            logger.warning("Bot 未构建（无 token），无法发送预警消息")
            return False

        try:
            bot = self._application.bot
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            return True
        except Forbidden:
            logger.warning(f"用户 {chat_id} 已屏蔽 Bot，无法发送预警")
            return False
        except NetworkError as e:
            logger.error(f"发送预警消息网络错误: {e}")
            return False
        except TelegramError as e:
            logger.error(f"发送预警消息失败: {e}")
            return False

    async def send_report(
        self,
        chat_id: int,
        message: str,
    ) -> bool:
        """发送报告消息（供 scheduler 模块调用）

        实现 IMessageSender.send_report。
        """
        if self._application is None:
            logger.warning("Bot 未构建（无 token），无法发送报告消息")
            return False

        try:
            bot = self._application.bot
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except Forbidden:
            logger.warning(f"用户 {chat_id} 已屏蔽 Bot，无法发送报告")
            return False
        except NetworkError as e:
            logger.error(f"发送报告消息网络错误: {e}")
            return False
        except TelegramError as e:
            logger.error(f"发送报告消息失败: {e}")
            return False

    # ──────────────────────────────────────────
    # 生命周期
    # ──────────────────────────────────────────

    async def run(self) -> None:
        """启动 Bot（polling 或 webhook）

        根据 config.telegram.mode 选择启动方式：
        - polling: 长轮询模式（适合无公网入口的 VPS）
        - webhook: Webhook 模式（适合有域名 + 反代的场景）
        """
        if self._application is None:
            logger.error(
                "Bot 未构建（缺少 bot_token），无法启动。"
                "请在配置文件中设置 telegram.bot_token。"
            )
            return

        app = self._application
        mode = self.config.telegram.mode

        logger.info(f"正在启动 Telegram Bot（模式: {mode}）...")

        # 初始化
        await app.initialize()
        self._initialized = True
        logger.info("Bot 已初始化")

        # 获取 Bot 信息
        me = await app.bot.get_me()
        logger.info(f"Bot 已连接: @{me.username} ({me.first_name})")

        # 注册命令菜单（输入框左侧 / 按钮展开的命令列表）
        from telegram import BotCommand
        commands = [
            BotCommand("status", "查看运行状态"),
            BotCommand("jails", "查看 Jail 列表"),
            BotCommand("banned", "查看封禁 IP"),
            BotCommand("jail", "查看指定 Jail 详情"),
            BotCommand("ban", "手动封禁 IP"),
            BotCommand("unban", "解封 IP"),
            BotCommand("report", "生成报告"),
            BotCommand("stats", "查看统计"),
            BotCommand("whitelist", "白名单管理"),
            BotCommand("setnotify", "开关通知"),
            BotCommand("setschedule", "设置定时报告"),
            BotCommand("f2bconfig", "Fail2ban 参数配置"),
            BotCommand("install", "安装 Fail2ban"),
            BotCommand("uninstall", "卸载 Fail2ban"),
            BotCommand("update", "更新 Fail2ban"),
            BotCommand("reload", "重载配置"),
            BotCommand("help", "使用帮助"),
        ]
        await app.bot.set_my_commands(commands)
        logger.info(f"已注册 {len(commands)} 条命令菜单")

        # 通知管理员 Bot 已上线
        await self._notify_admins_online()

        try:
            await app.start()

            if mode == "webhook":
                await self._start_webhook(app)
            else:
                await self._start_polling(app)

            logger.info("Bot 已启动，等待消息...")

            # 保持运行，直到收到停止信号
            stop_event = asyncio.Event()
            # 注册信号处理（在 asyncio 事件循环中）
            try:
                import signal

                loop = asyncio.get_running_loop()
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.add_signal_handler(sig, stop_event.set)
            except (NotImplementedError, RuntimeError):
                # Windows 不支持 add_signal_handler
                pass

            await stop_event.wait()

        except KeyboardInterrupt:
            logger.info("收到中断信号，正在停止...")
        finally:
            await self.shutdown()

    async def _start_polling(self, app: Application) -> None:
        """启动 polling 模式"""
        await app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        logger.info("Polling 已启动")

    async def _start_webhook(self, app: Application) -> None:
        """启动 webhook 模式"""
        tg = self.config.telegram
        await app.updater.start_webhook(
            listen="0.0.0.0",
            port=tg.webhook_port,
            url_path=tg.bot_token.split(":")[0] if tg.bot_token else "",
            webhook_url=tg.webhook_url,
            allowed_updates=Update.ALL_TYPES,
        )
        logger.info(f"Webhook 已启动 (port={tg.webhook_port})")

    async def _notify_admins_online(self) -> None:
        """通知管理员 Bot 已上线"""
        if not self.config.telegram.admin_chat_ids:
            return

        message = (
            "\U0001f7e2 <b>f2b-manager Bot 已上线</b>\n\n"
            f"Bot 已成功启动，随时待命。\n"
            "输入 /help 查看可用命令。"
        )

        for admin_id in self.config.telegram.admin_chat_ids:
            try:
                await self.send_alert(admin_id, message)
            except Exception as e:
                logger.debug(f"通知管理员 {admin_id} 失败: {e}")

    async def shutdown(self) -> None:
        """关闭 Bot，释放资源"""
        if self._application is None:
            return

        app = self._application

        logger.info("正在停止 Telegram Bot...")

        try:
            if app.updater and app.updater.running:
                await app.updater.stop()
                logger.info("Updater 已停止")

            if app.running:
                await app.stop()
                logger.info("Application 已停止")

            if self._initialized:
                await app.shutdown()
                logger.info("Application 已关闭")
        except Exception as e:
            logger.error(f"关闭 Bot 时出错: {e}")

        self._initialized = False
        logger.info("Telegram Bot 已停止")

    # ──────────────────────────────────────────
    # 全局错误处理
    # ──────────────────────────────────────────

    async def error_handler(
        self, update: object, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """全局错误处理器"""
        error = context.error
        if error is None:
            return

        logger.error(
            f"处理更新时出错: {error}",
            exc_info=context.error,
        )

        # 尝试通知用户
        if isinstance(update, Update) and update.effective_chat:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=format_error(
                        "处理命令时发生内部错误，请稍后重试。\n"
                        "如问题持续，请联系管理员查看日志。"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass  # 避免错误处理本身再报错

    # ──────────────────────────────────────────
    # 开发/测试辅助
    # ──────────────────────────────────────────

    @property
    def application(self) -> Optional[Application]:
        """暴露 Application 供外部测试"""
        return self._application

    @property
    def is_ready(self) -> bool:
        """Bot 是否已就绪（有 token 且已构建）"""
        return self._application is not None
