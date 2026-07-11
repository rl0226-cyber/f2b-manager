"""
f2b_manager.telegram_bot.deps
=============================

共享依赖容器。

Bot 在初始化时将 config / f2b_manager / installer / db / auth 打包为
BotDeps 存入 Application.bot_data["deps"]，所有 handler 通过 get_deps()
统一获取，避免循环导入。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

    from ..config import AppConfig
    from ..storage.database import StateDB
    from ..storage.models import IFail2banInstaller, IFail2banManager
    from .auth import AuthManager


@dataclass
class BotDeps:
    """Bot 运行时共享依赖（注入到 Application.bot_data）"""

    config: "AppConfig"
    f2b_manager: Optional["IFail2banManager"] = None
    installer: Optional["IFail2banInstaller"] = None
    db: Optional["StateDB"] = None
    auth: Optional["AuthManager"] = None

    # ── 便捷属性 ──────────────────────────────

    @property
    def tg(self) -> "Any":
        """TelegramConfig 快捷访问"""
        return self.config.telegram

    @property
    def f2b(self) -> Optional["IFail2banManager"]:
        return self.f2b_manager

    def get_installer(self) -> Optional["IFail2banInstaller"]:
        """获取安装器：优先用显式注入的 installer，
        其次回退检查 f2b_manager 是否自带安装方法（鸭子类型）。"""
        if self.installer is not None:
            return self.installer
        if self.f2b_manager is not None and hasattr(self.f2b_manager, "install"):
            return self.f2b_manager  # type: ignore[return-value]
        return None


def get_deps(context: "ContextTypes.DEFAULT_TYPE") -> BotDeps:
    """从 context.bot_data 获取 BotDeps"""
    return context.bot_data["deps"]


def f2b_not_ready() -> str:
    """f2b_manager 未就绪时的标准提示"""
    return (
        "⚠️ <b>功能尚未就绪</b>\n\n"
        "Fail2ban 管理模块 (M1) 尚未加载。\n"
        "请在服务器上安装并运行 f2b-manager 后重试。"
    )
