"""
f2b_manager.config
==================

配置加载与校验。

从 YAML 文件加载配置，提供类型安全的访问接口。
支持默认值合并、环境变量覆盖和运行时配置覆盖（通过 StateDB）。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class TelegramConfig:
    """Telegram Bot 配置"""
    bot_token: str = ""
    admin_chat_ids: list[int] = field(default_factory=list)
    operator_chat_ids: list[int] = field(default_factory=list)
    notify_chat_id: int = 0
    mode: str = "polling"  # polling | webhook
    webhook_url: str = ""
    webhook_port: int = 8443
    # 限流
    max_messages_per_minute: int = 20
    cooldown_on_burst: int = 60


@dataclass
class Fail2banConfig:
    """Fail2ban 配置"""
    default_bantime: str = "1h"
    default_findtime: str = "10m"
    default_maxretry: int = 5
    incremental: bool = True
    max_bantime: str = "1w"
    ignoreip: list[str] = field(default_factory=lambda: ["127.0.0.1/8", "::1"])
    enabled_jails: list[str] = field(default_factory=lambda: ["sshd"])


@dataclass
class ScheduleConfig:
    """定时任务配置"""
    daily_report_enabled: bool = True
    daily_report_time: str = "08:00"
    weekly_report_enabled: bool = True
    weekly_report_day: str = "monday"
    weekly_report_time: str = "08:00"
    poll_interval_minutes: int = 5
    health_check_minutes: int = 10


@dataclass
class NotifyConfig:
    """通知配置"""
    enable_ban_alert: bool = True
    enable_unban_alert: bool = False
    enable_service_alert: bool = True
    enable_health_alert: bool = True
    # GeoIP
    geoip_enabled: bool = True
    geoip_method: str = "local"  # local | api
    geoip_db_path: str = "/var/lib/GeoIP/GeoLite2-Country.mmdb"
    # 去重窗口
    dedup_window_seconds: int = 300


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str = "INFO"
    file: str = "/var/log/f2b-manager.log"
    max_size_mb: int = 10
    backup_count: int = 5


@dataclass
class DatabaseConfig:
    """数据库配置"""
    path: str = "/var/lib/f2b-manager/state.db"


@dataclass
class AppConfig:
    """应用全局配置"""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    fail2ban: Fail2banConfig = field(default_factory=Fail2banConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)

    # 运行时填充
    config_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        """从字典构造配置（合并默认值）"""
        cfg = cls()

        tg = data.get("telegram", {})
        cfg.telegram = TelegramConfig(
            bot_token=tg.get("bot_token", os.getenv("F2B_BOT_TOKEN", "")),
            admin_chat_ids=tg.get("admin_chat_ids", []),
            operator_chat_ids=tg.get("operator_chat_ids", []),
            notify_chat_id=tg.get("notify_chat_id", 0),
            mode=tg.get("mode", "polling"),
            webhook_url=tg.get("webhook", {}).get("url", ""),
            webhook_port=tg.get("webhook", {}).get("port", 8443),
            max_messages_per_minute=tg.get("rate_limit", {}).get(
                "max_messages_per_minute", 20
            ),
            cooldown_on_burst=tg.get("rate_limit", {}).get(
                "cooldown_on_burst", 60
            ),
        )

        f2b = data.get("fail2ban", {})
        cfg.fail2ban = Fail2banConfig(
            default_bantime=f2b.get("default_bantime", "1h"),
            default_findtime=f2b.get("default_findtime", "10m"),
            default_maxretry=f2b.get("default_maxretry", 5),
            incremental=f2b.get("incremental", True),
            max_bantime=f2b.get("max_bantime", "1w"),
            ignoreip=f2b.get("ignoreip", ["127.0.0.1/8", "::1"]),
            enabled_jails=f2b.get("enabled_jails", ["sshd"]),
        )

        sch = data.get("schedule", {})
        daily = sch.get("daily_report", {})
        weekly = sch.get("weekly_report", {})
        cfg.schedule = ScheduleConfig(
            daily_report_enabled=daily.get("enabled", True),
            daily_report_time=daily.get("time", "08:00"),
            weekly_report_enabled=weekly.get("enabled", True),
            weekly_report_day=weekly.get("day", "monday"),
            weekly_report_time=weekly.get("time", "08:00"),
            poll_interval_minutes=sch.get("poll_interval_minutes", 5),
            health_check_minutes=sch.get("health_check_minutes", 10),
        )

        ntf = data.get("notify", {})
        geoip = ntf.get("geoip", {})
        cfg.notify = NotifyConfig(
            enable_ban_alert=ntf.get("enable_ban_alert", True),
            enable_unban_alert=ntf.get("enable_unban_alert", False),
            enable_service_alert=ntf.get("enable_service_alert", True),
            enable_health_alert=ntf.get("enable_health_alert", True),
            geoip_enabled=geoip.get("enabled", True),
            geoip_method=geoip.get("method", "local"),
            geoip_db_path=geoip.get(
                "db_path", "/var/lib/GeoIP/GeoLite2-Country.mmdb"
            ),
            dedup_window_seconds=ntf.get("dedup_window_seconds", 300),
        )

        log = data.get("logging", {})
        cfg.logging = LoggingConfig(
            level=log.get("level", "INFO"),
            file=log.get("file", "/var/log/f2b-manager.log"),
            max_size_mb=log.get("max_size_mb", 10),
            backup_count=log.get("backup_count", 5),
        )

        db = data.get("database", {})
        cfg.database = DatabaseConfig(
            path=db.get("path", "/var/lib/f2b-manager/state.db"),
        )

        return cfg

    def validate(self) -> list[str]:
        """校验配置，返回错误信息列表（空列表表示通过）"""
        errors: list[str] = []

        if not self.telegram.bot_token:
            errors.append("telegram.bot_token 未设置")
        if self.telegram.notify_chat_id == 0:
            errors.append("telegram.notify_chat_id 未设置")
        if not self.telegram.admin_chat_ids:
            errors.append("telegram.admin_chat_ids 未设置（至少需要一个管理员）")

        if self.telegram.mode not in ("polling", "webhook"):
            errors.append(f"telegram.mode 无效: {self.telegram.mode}")
        if self.telegram.mode == "webhook" and not self.telegram.webhook_url:
            errors.append("webhook 模式需要设置 webhook.url")

        if self.schedule.poll_interval_minutes < 1:
            errors.append("schedule.poll_interval_minutes 不能小于 1")
        if self.schedule.health_check_minutes < 1:
            errors.append("schedule.health_check_minutes 不能小于 1")

        return errors

    def to_dict(self) -> dict[str, Any]:
        """将配置序列化为 YAML 友好的字典（仅写入非默认值的关键字段）"""
        # Telegram
        telegram_dict: dict[str, Any] = {
            "bot_token": self.telegram.bot_token,
            "admin_chat_ids": self.telegram.admin_chat_ids,
            "operator_chat_ids": self.telegram.operator_chat_ids,
            "notify_chat_id": self.telegram.notify_chat_id,
            "mode": self.telegram.mode,
        }
        if self.telegram.mode == "webhook":
            telegram_dict["webhook"] = {
                "url": self.telegram.webhook_url,
                "port": self.telegram.webhook_port,
            }
        telegram_dict["rate_limit"] = {
            "max_messages_per_minute": self.telegram.max_messages_per_minute,
            "cooldown_on_burst": self.telegram.cooldown_on_burst,
        }

        # Fail2ban
        fail2ban_dict: dict[str, Any] = {
            "default_bantime": self.fail2ban.default_bantime,
            "default_findtime": self.fail2ban.default_findtime,
            "default_maxretry": self.fail2ban.default_maxretry,
            "incremental": self.fail2ban.incremental,
            "max_bantime": self.fail2ban.max_bantime,
            "ignoreip": self.fail2ban.ignoreip,
            "enabled_jails": self.fail2ban.enabled_jails,
        }

        # Schedule
        schedule_dict: dict[str, Any] = {
            "daily_report": {
                "enabled": self.schedule.daily_report_enabled,
                "time": self.schedule.daily_report_time,
            },
            "weekly_report": {
                "enabled": self.schedule.weekly_report_enabled,
                "day": self.schedule.weekly_report_day,
                "time": self.schedule.weekly_report_time,
            },
            "poll_interval_minutes": self.schedule.poll_interval_minutes,
            "health_check_minutes": self.schedule.health_check_minutes,
        }

        # Notify
        notify_dict: dict[str, Any] = {
            "enable_ban_alert": self.notify.enable_ban_alert,
            "enable_unban_alert": self.notify.enable_unban_alert,
            "enable_service_alert": self.notify.enable_service_alert,
            "enable_health_alert": self.notify.enable_health_alert,
            "geoip": {
                "enabled": self.notify.geoip_enabled,
                "method": self.notify.geoip_method,
                "db_path": self.notify.geoip_db_path,
            },
            "dedup_window_seconds": self.notify.dedup_window_seconds,
        }

        # Logging
        logging_dict: dict[str, Any] = {
            "level": self.logging.level,
            "file": self.logging.file,
            "max_size_mb": self.logging.max_size_mb,
            "backup_count": self.logging.backup_count,
        }

        # Database
        database_dict: dict[str, Any] = {
            "path": self.database.path,
        }

        return {
            "telegram": telegram_dict,
            "fail2ban": fail2ban_dict,
            "schedule": schedule_dict,
            "notify": notify_dict,
            "logging": logging_dict,
            "database": database_dict,
        }


def save_config(config: AppConfig, config_path: str) -> None:
    """将配置写回 YAML 文件（保留可读格式）

    - 序列化 AppConfig 为 YAML 字典
    - 如果文件已存在，先备份为 config.yaml.bak
    - 写入后设置文件权限 600
    """
    path = Path(config_path)

    # 备份旧文件
    if path.exists():
        backup_path = Path(str(path) + ".bak")
        shutil.copy2(path, backup_path)

    # 确保父目录存在
    path.parent.mkdir(parents=True, exist_ok=True)

    # 序列化并写入
    data = config.to_dict()
    yaml_content = yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        indent=2,
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("# f2b-manager 配置文件\n")
        f.write("# 部署后路径: /etc/f2b-manager/config.yaml (权限 600)\n\n")
        f.write(yaml_content)

    # 设置权限 600
    path.chmod(0o600)


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """加载配置文件

    查找顺序:
    1. 显式传入的 config_path
    2. 环境变量 F2B_CONFIG
    3. /etc/f2b-manager/config.yaml
    4. ./config/config.yaml (开发环境)
    """
    if config_path is None:
        config_path = os.getenv(
            "F2B_CONFIG",
            "/etc/f2b-manager/config.yaml",
        )

    path = Path(config_path)
    if not path.exists():
        # 开发环境回退
        dev_path = Path("config/config.yaml")
        if dev_path.exists():
            path = dev_path
        else:
            # 返回默认配置（未初始化状态）
            cfg = AppConfig()
            cfg.config_path = str(path)
            return cfg

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    cfg = AppConfig.from_dict(data)
    cfg.config_path = str(path)
    return cfg
