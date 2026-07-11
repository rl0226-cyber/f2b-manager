"""f2b_manager.notify 包 - 实时预警模块

提供 IP 归属地查询、消息去重限流和预警消息构造与发送功能。
通过 fail2ban 自定义 action (telegram-notify.conf) + 桥接脚本
(f2b-notify.sh) 接收 fail2ban 事件，经 CLI notify 子命令转发到
本模块处理。
"""

from .geoip import GeoIPLookup
from .dedup import DedupTracker
from .sender import AlertSender, BAN_TEMPLATE, UNBAN_TEMPLATE

__all__ = [
    "GeoIPLookup",
    "DedupTracker",
    "AlertSender",
    "BAN_TEMPLATE",
    "UNBAN_TEMPLATE",
]
