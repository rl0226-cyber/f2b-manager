"""
f2b_manager.notify.dedup
========================

消息去重限流器。

基于 (ip, jail) 维度在时间窗口内去重：同一 IP 在同一个 jail 中，
在 dedup_window_seconds 秒内只发送一次预警通知。

线程安全：内部使用 threading.Lock 保护共享状态。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple

logger = logging.getLogger("notify.dedup")


class DedupTracker:
    """消息去重追踪器。

    用内存字典记录每个 (ip, jail) 组合最近一次通知的时间戳。
    同组合在时间窗口内的后续请求会被抑制。

    线程安全：所有读写操作由 threading.Lock 保护。
    """

    def __init__(self, window_seconds: int = 300):
        """
        Args:
            window_seconds: 去重时间窗口（秒），默认 300 秒（5 分钟）。
        """
        self._window = window_seconds
        self._lock = threading.Lock()
        # {(ip, jail): last_notify_timestamp}
        self._last_notify: dict[Tuple[str, str], float] = {}

    def should_send(self, ip: str, jail: str) -> bool:
        """判断是否应该发送该事件的通知。

        Args:
            ip: 被操作的 IP 地址
            jail: fail2ban jail 名称

        Returns:
            True 表示应该发送通知（不在窗口内或首次出现），
            False 表示应该跳过（在去重窗口内）。
        """
        key = (ip, jail)
        now = time.time()

        with self._lock:
            last_time = self._last_notify.get(key)

            if last_time is not None and (now - last_time) < self._window:
                elapsed = now - last_time
                logger.debug(
                    "去重跳过: ip=%s jail=%s 距离上次通知仅 %.0f 秒 (窗口=%d秒)",
                    ip, jail, elapsed, self._window,
                )
                return False

            # 更新通知时间
            self._last_notify[key] = now
            return True

    def reset(self, ip: str, jail: str) -> None:
        """重置指定组合的去重状态（用于解封等场景强制通知）。

        Args:
            ip: IP 地址
            jail: jail 名称
        """
        key = (ip, jail)
        with self._lock:
            self._last_notify.pop(key, None)

    def reset_all(self) -> None:
        """清空所有去重状态。"""
        with self._lock:
            self._last_notify.clear()

    def cleanup(self, max_age_seconds: Optional[int] = None) -> int:
        """清理过期的去重记录。

        Args:
            max_age_seconds: 超过此时间的记录将被清理。
                             默认使用 window_seconds * 2。

        Returns:
            清理的记录数。
        """
        if max_age_seconds is None:
            max_age_seconds = self._window * 2

        now = time.time()
        cutoff = now - max_age_seconds
        removed = 0

        with self._lock:
            stale_keys = [
                k for k, t in self._last_notify.items()
                if t < cutoff
            ]
            for k in stale_keys:
                del self._last_notify[k]
            removed = len(stale_keys)

        if removed:
            logger.debug("清理了 %d 条过期去重记录 (窗口*2=%d秒)",
                         removed, max_age_seconds)

        return removed

    def __len__(self) -> int:
        """返回当前追踪组合数。"""
        with self._lock:
            return len(self._last_notify)
