"""
tests/test_dedup.py
===================
去重限流逻辑测试。

覆盖: 首次通知放行 / 窗口内去重 / 窗口过期后放行 / 不同 IP 不影响 /
       reset / reset_all / cleanup / 线程安全。
"""
from __future__ import annotations

import time
import threading

import pytest

from f2b_manager.notify.dedup import DedupTracker


class TestShouldSend:
    """去重判断测试"""

    def test_first_call_allows(self):
        """首次调用应允许发送。"""
        tracker = DedupTracker(window_seconds=300)
        assert tracker.should_send("1.2.3.4", "sshd") is True

    def test_second_call_within_window_blocks(self):
        """窗口内重复调用应被阻止。"""
        tracker = DedupTracker(window_seconds=300)
        assert tracker.should_send("1.2.3.4", "sshd") is True
        assert tracker.should_send("1.2.3.4", "sshd") is False

    def test_after_window_expires_allows(self):
        """窗口过期后应允许重新发送。"""
        tracker = DedupTracker(window_seconds=1)
        assert tracker.should_send("1.2.3.4", "sshd") is True
        assert tracker.should_send("1.2.3.4", "sshd") is False

        # 等待窗口过期
        time.sleep(1.1)
        assert tracker.should_send("1.2.3.4", "sshd") is True

    def test_different_ips_dont_interfere(self):
        """不同 IP 的去重互不影响。"""
        tracker = DedupTracker(window_seconds=300)
        assert tracker.should_send("1.2.3.4", "sshd") is True
        assert tracker.should_send("5.6.7.8", "sshd") is True
        # 第一个 IP 被去重
        assert tracker.should_send("1.2.3.4", "sshd") is False
        # 第二个 IP 也被去重
        assert tracker.should_send("5.6.7.8", "sshd") is False

    def test_different_jails_dont_interfere(self):
        """同一 IP 不同 jail 的去重互不影响。"""
        tracker = DedupTracker(window_seconds=300)
        assert tracker.should_send("1.2.3.4", "sshd") is True
        assert tracker.should_send("1.2.3.4", "nginx-http-auth") is True
        # sshd 的去重不影响
        assert tracker.should_send("1.2.3.4", "sshd") is False
        assert tracker.should_send("1.2.3.4", "nginx-http-auth") is False

    def test_same_ip_same_jail_same_window_blocks(self):
        """同一 IP 同一 jail 在同一窗口内被去重。"""
        tracker = DedupTracker(window_seconds=10)
        assert tracker.should_send("10.0.0.1", "recidive") is True
        for _ in range(5):
            assert tracker.should_send("10.0.0.1", "recidive") is False

    def test_custom_window(self):
        """自定义窗口时间生效。"""
        tracker = DedupTracker(window_seconds=2)
        assert tracker.should_send("1.2.3.4", "sshd") is True
        assert tracker.should_send("1.2.3.4", "sshd") is False
        time.sleep(2.1)
        assert tracker.should_send("1.2.3.4", "sshd") is True


class TestReset:
    """重置操作测试"""

    def test_reset_single(self):
        """重置单个组合的去重状态。"""
        tracker = DedupTracker(window_seconds=300)
        tracker.should_send("1.2.3.4", "sshd")
        assert tracker.should_send("1.2.3.4", "sshd") is False

        tracker.reset("1.2.3.4", "sshd")
        # 重置后应允许发送
        assert tracker.should_send("1.2.3.4", "sshd") is True

    def test_reset_all(self):
        """清空所有去重状态。"""
        tracker = DedupTracker(window_seconds=300)
        tracker.should_send("1.2.3.4", "sshd")
        tracker.should_send("5.6.7.8", "nginx-http-auth")

        assert len(tracker) == 2
        tracker.reset_all()
        assert len(tracker) == 0

        # 重置后都可以发送
        assert tracker.should_send("1.2.3.4", "sshd") is True
        assert tracker.should_send("5.6.7.8", "nginx-http-auth") is True

    def test_reset_nonexistent_no_error(self):
        """重置不存在的组合不报错。"""
        tracker = DedupTracker()
        tracker.reset("nonexistent", "jail")

    def test_len_tracking(self):
        """__len__ 正确追踪组合数。"""
        tracker = DedupTracker(window_seconds=300)
        assert len(tracker) == 0

        tracker.should_send("1.2.3.4", "sshd")
        assert len(tracker) == 1

        tracker.should_send("1.2.3.4", "sshd")  # 重复不计
        assert len(tracker) == 1

        tracker.should_send("5.6.7.8", "sshd")
        assert len(tracker) == 2

        tracker.should_send("1.2.3.4", "nginx-http-auth")
        assert len(tracker) == 3


class TestCleanup:
    """过期记录清理测试"""

    def test_cleanup_removes_stale(self):
        """清理应移除过期的记录。"""
        tracker = DedupTracker(window_seconds=1)
        tracker.should_send("1.2.3.4", "sshd")

        # 等待记录过期
        time.sleep(2.1)

        removed = tracker.cleanup(max_age_seconds=1)
        assert removed == 1
        assert len(tracker) == 0

    def test_cleanup_keeps_fresh(self):
        """清理应保留未过期的记录。"""
        tracker = DedupTracker(window_seconds=300)
        tracker.should_send("1.2.3.4", "sshd")

        removed = tracker.cleanup(max_age_seconds=600)
        assert removed == 0
        assert len(tracker) == 1

    def test_cleanup_default_uses_2x_window(self):
        """默认清理时间使用 2 倍窗口。"""
        tracker = DedupTracker(window_seconds=1)
        tracker.should_send("1.2.3.4", "sshd")
        time.sleep(2.1)

        # 默认 max_age = 2*window = 2 秒，记录已过期
        removed = tracker.cleanup()
        assert removed == 1

    def test_cleanup_empty(self):
        """空 tracker 清理不报错。"""
        tracker = DedupTracker()
        removed = tracker.cleanup()
        assert removed == 0


class TestThreadSafety:
    """线程安全测试"""

    def test_concurrent_access(self):
        """多线程并发不应崩溃或丢失数据。"""
        tracker = DedupTracker(window_seconds=10)
        errors = []

        def worker(ip_prefix: str):
            try:
                for i in range(50):
                    ip = f"{ip_prefix}.{i % 256}.{i % 256}"
                    tracker.should_send(ip, "sshd")
            except Exception as e:
                errors.append(e)

        threads = []
        for prefix in range(4):
            t = threading.Thread(target=worker, args=(f"10.{prefix}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        # 应该有 4*50 = 200 条记录（首次都放行）
        assert len(tracker) == 200
