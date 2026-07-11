"""
f2b_manager.storage.models
==========================

全局数据模型与接口契约定义。

本文件是整个项目的「契约层」——所有跨模块共享的数据类型和 Protocol 接口
都在此定义。其他模块（fail2ban/、telegram_bot/、monitor/、notify/）开发时
必须严格依赖此处的类型签名，而非具体实现。

开发期可用 Mock 实现替代未完成的依赖模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable


# ──────────────────────────────────────────────
# 枚举
# ──────────────────────────────────────────────

class Distro(str, Enum):
    """Linux 发行版类型"""
    DEBIAN = "debian"
    UBUNTU = "ubuntu"
    CENTOS = "centos"
    RHEL = "rhel"
    ROCKY = "rocky"
    ALMA = "alma"
    FEDORA = "fedora"
    ALPINE = "alpine"
    ARCH = "arch"
    UNKNOWN = "unknown"


class PackageManager(str, Enum):
    """包管理器类型"""
    APT = "apt"
    DNF = "dnf"
    YUM = "yum"
    APK = "apk"
    PACMAN = "pacman"
    UNKNOWN = "unknown"


class BanAction(str, Enum):
    """封禁动作类型"""
    BAN = "ban"
    UNBAN = "unban"
    START = "start"
    STOP = "stop"


class AuthLevel(int, Enum):
    """Telegram 用户权限等级（数值越大权限越高）"""
    VIEWER = 1     # 仅 /start /help
    OPERATOR = 2   # 查询 + 报告 + 通知开关
    ADMIN = 3      # 全部操作：安装/卸载/更新/封禁


class ServiceState(str, Enum):
    """fail2ban 服务运行状态"""
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


# ──────────────────────────────────────────────
# 数据模型 (dataclass)
# ──────────────────────────────────────────────

@dataclass
class DistroInfo:
    """发行版信息"""
    distro: Distro
    version: str
    package_manager: PackageManager


@dataclass
class Fail2banStatus:
    """fail2ban 整体状态"""
    version: str = ""
    state: ServiceState = ServiceState.UNKNOWN
    jail_count: int = 0
    total_bans: int = 0
    uptime: str = ""


@dataclass
class JailInfo:
    """单个 jail 基本信息"""
    name: str
    enabled: bool = True
    current_ban: int = 0
    total_failed: int = 0
    total_banned: int = 0


@dataclass
class JailStatus(JailInfo):
    """单个 jail 详细状态（含封禁 IP 列表）"""
    banned_ips: list[str] = field(default_factory=list)
    findtime: str = ""
    bantime: str = ""
    maxretry: int = 0


@dataclass
class BanEvent:
    """封禁/解封事件（从 fail2ban action hook 接收）"""
    ip: str
    jail: str
    action: BanAction
    failures: int = 0
    matches: str = ""
    country: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class InstallResult:
    """安装/卸载/更新操作结果"""
    success: bool
    message: str = ""
    version: str = ""
    old_version: str = ""
    details: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass
class DailyStat:
    """每日封禁统计"""
    date: str
    total_bans: int = 0
    unique_ips: int = 0
    top_country: str = ""


@dataclass
class BanChange:
    """轮询对比发现的封禁变化"""
    added: list[tuple[str, str]] = field(default_factory=list)   # [(ip, jail), ...]
    removed: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class GeoInfo:
    """IP 归属地信息"""
    country: str = ""
    country_code: str = ""
    flag: str = ""


# ──────────────────────────────────────────────
# Protocol 接口契约
# ──────────────────────────────────────────────

@runtime_checkable
class IFail2banManager(Protocol):
    """Fail2ban 运行时管理接口（M1 实现）"""

    def get_status(self) -> Fail2banStatus:
        """获取 fail2ban 整体状态"""
        ...

    def get_jails(self) -> list[JailInfo]:
        """获取所有启用的 jail 列表"""
        ...

    def get_jail_status(self, jail: str) -> JailStatus:
        """获取指定 jail 的详细状态"""
        ...

    def get_banned_ips(self) -> list[str]:
        """获取所有 jail 中当前被封禁的 IP"""
        ...

    def ban_ip(self, ip: str, jail: str = "sshd") -> bool:
        """手动封禁 IP"""
        ...

    def unban_ip(self, ip: str) -> bool:
        """解封 IP"""
        ...

    def reload(self) -> bool:
        """重载 fail2ban 配置"""
        ...


@runtime_checkable
class IFail2banInstaller(Protocol):
    """Fail2ban 安装/卸载/更新接口（M1 实现）"""

    def install(self) -> InstallResult:
        """安装 fail2ban"""
        ...

    def uninstall(self, keep_config: bool = True) -> InstallResult:
        """卸载 fail2ban"""
        ...

    def update(self) -> InstallResult:
        """更新 fail2ban"""
        ...


@runtime_checkable
class IMessageSender(Protocol):
    """消息发送接口（M2 Bot 实现，M3/M4 调用）"""

    async def send_alert(self, chat_id: int, message: str,
                         parse_mode: str = "HTML") -> bool:
        """发送预警消息"""
        ...

    async def send_report(self, chat_id: int, message: str) -> bool:
        """发送报告消息"""
        ...


@runtime_checkable
class IAlertSender(Protocol):
    """实时预警发送接口（M3 实现，M4 调用）"""

    async def send_ban_alert(self, event: BanEvent) -> bool:
        """发送封禁预警"""
        ...

    async def send_service_alert(self, action: BanAction, jail: str = "") -> bool:
        """发送服务启停通知"""
        ...


@runtime_checkable
class IStateDB(Protocol):
    """状态库接口（storage/database.py 实现）"""

    def record_ban(self, event: BanEvent) -> None:
        """记录封禁事件到历史表"""
        ...

    def get_current_bans(self) -> list[tuple[str, str]]:
        """获取当前封禁快照 [(ip, jail), ...]"""
        ...

    def set_current_bans(self, bans: list[tuple[str, str]]) -> None:
        """更新当前封禁快照"""
        ...

    def get_ban_history(self, days: int = 7) -> list[BanEvent]:
        """查询最近 N 天的封禁历史"""
        ...

    def get_daily_stats(self, days: int = 7) -> list[DailyStat]:
        """查询每日统计"""
        ...

    def set_config_override(self, key: str, value: str) -> None:
        """设置配置覆盖项"""
        ...

    def get_config_override(self, key: str, default: str = "") -> str:
        """读取配置覆盖项"""
        ...


@runtime_checkable
class IReporter(Protocol):
    """报告生成接口（M4 实现）"""

    def daily_report(self) -> str:
        """生成每日报告文本"""
        ...

    def weekly_report(self) -> str:
        """生成每周报告文本"""
        ...

    def instant_report(self) -> str:
        """生成即时报告文本"""
        ...
