"""
f2b_manager.app
===============

应用主类，组装各模块并管理生命周期。

Wave 1 (M0) 阶段为骨架实现，各子模块在 Wave 2+ 逐步接入。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .config import AppConfig
from .storage.database import StateDB
from .storage.models import (
    IFail2banInstaller, IFail2banManager,
    IAlertSender, IMessageSender, IReporter,
)
from .utils.logger import get_logger


class Application:
    """f2b-manager 应用主类

    负责组装各模块、管理生命周期：
    - 加载配置
    - 初始化状态库
    - 启动 Telegram Bot (M2, Wave 2)
    - 启动 Scheduler (M4, Wave 3)
    - 接收通知事件 (M3, Wave 2)

    生命周期:
        app = Application(config)
        app.setup()    # 初始化各模块
        app.run()      # 进入主循环
        app.shutdown() # 清理资源
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = get_logger("app")

        # 核心组件（M0 直接初始化）
        self.db: Optional[StateDB] = None

        # 子模块（Wave 2+ 注入）
        self._f2b_manager: Optional[IFail2banManager] = None
        self._f2b_installer: Optional[IFail2banInstaller] = None
        self._bot: Optional[IMessageSender] = None
        self._alert_sender: Optional[IAlertSender] = None
        self._reporter: Optional[IReporter] = None
        self._scheduler = None  # APScheduler 实例

        self._running = False

    def setup(self) -> None:
        """初始化各模块"""
        self.logger.info("正在初始化 f2b-manager...")

        # 1. 状态库
        self.db = StateDB(self.config.database.path)
        self.logger.info(f"状态库已连接: {self.config.database.path}")

        # 2. Fail2ban 管理模块 (M1, Wave 2)
        try:
            from .fail2ban.manager import Fail2banManager
            from .fail2ban.installer import Fail2banInstaller
            self._f2b_manager = Fail2banManager(self.config)
            self._f2b_installer = Fail2banInstaller(self.config)
            self.logger.info("Fail2ban 管理模块已加载")
        except ImportError:
            self.logger.debug("Fail2ban 管理模块待实现 (M1)")

        # 3. Telegram Bot (M2, Wave 2)
        try:
            from .telegram_bot.bot import F2BTelegramBot
            self._bot = F2BTelegramBot(
                config=self.config,
                f2b_manager=self._f2b_manager,
                db=self.db,
            )
            self.logger.info("Telegram Bot 模块已加载")
        except ImportError:
            self.logger.debug("Telegram Bot 模块待实现 (M2)")

        # 4. 实时预警 (M3, Wave 2)
        try:
            from .notify.sender import AlertSender
            self._alert_sender = AlertSender(
                config=self.config,
                bot=self._bot,
                db=self.db,
            )
            self.logger.info("实时预警模块已加载")
        except ImportError:
            self.logger.debug("实时预警模块待实现 (M3)")

        # 5. 定时任务 (M4, Wave 3)
        try:
            from .monitor.scheduler import F2BScheduler
            self._scheduler = F2BScheduler(
                config=self.config,
                f2b_manager=self._f2b_manager,
                bot=self._bot,
                alert_sender=self._alert_sender,
                db=self.db,
            )
            self.logger.info("定时任务模块已加载")
        except ImportError:
            self.logger.debug("定时任务模块待实现 (M4)")

        self.logger.info("初始化完成")

    def run(self) -> None:
        """启动主循环"""
        self.setup()
        self._running = True

        self.logger.info("f2b-manager 守护进程已启动")
        self.logger.info(f"配置文件: {self.config.config_path}")

        # Wave 2+ 实现：启动 Bot + Scheduler 的异步事件循环
        # 当前 M0 阶段：保持进程运行，等待子模块实现
        try:
            if self._bot is not None and hasattr(self._bot, "run"):
                # M2 实现后：Bot 的 run() 会启动事件循环 + scheduler
                asyncio.run(self._bot.run())
            else:
                # M0 阶段：占位运行
                self.logger.info("M0 基础设施已就绪，等待 Wave 2 模块实现")
                self.logger.info("当前可用的 CLI 命令:")
                self.logger.info("  f2b-manager status       - 查看 fail2ban 状态")
                self.logger.info("  f2b-manager fail2ban install - 安装 fail2ban")
                self.logger.info("  f2b-manager --help       - 查看所有命令")
                # 保持运行
                while self._running:
                    asyncio.sleep(60)
        except KeyboardInterrupt:
            self.logger.info("收到中断信号")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """清理资源"""
        self.logger.info("正在关闭 f2b-manager...")
        self._running = False

        if self._scheduler:
            try:
                self._scheduler.shutdown()
            except Exception as e:
                self.logger.error(f"关闭 Scheduler 失败: {e}")

        if self._bot and hasattr(self._bot, "shutdown"):
            try:
                asyncio.run(self._bot.shutdown())
            except Exception as e:
                self.logger.error(f"关闭 Bot 失败: {e}")

        if self.db:
            self.db.close()
            self.logger.info("状态库已关闭")

        self.logger.info("f2b-manager 已停止")
