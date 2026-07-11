"""
tests/test_database.py
======================
StateDB 数据模型测试。

覆盖: record_ban / get_ban_history / set_current_bans / get_current_bans /
       update_daily_stats / get_daily_stats / count_bans_today /
       top_banned_ips / top_banned_countries / config_overrides

边界条件: 空表、大量数据、重复记录、异常参数。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from f2b_manager.storage.models import BanAction, BanEvent, DailyStat


class TestRecordBan:
    """封禁事件记录测试"""

    def test_record_single(self, tmp_db):
        """记录单条封禁事件，验证数据完整性。"""
        event = BanEvent(
            ip="192.0.2.1",
            jail="sshd",
            action=BanAction.BAN,
            failures=3,
            country="US",
            matches="auth.log line 42",
            timestamp=datetime(2026, 7, 1, 12, 0, 0),
        )
        tmp_db.record_ban(event)

        history = tmp_db.get_ban_history(days=365)
        assert len(history) == 1
        assert history[0].ip == "192.0.2.1"
        assert history[0].jail == "sshd"
        assert history[0].action == BanAction.BAN
        assert history[0].failures == 3
        assert history[0].country == "US"

    def test_record_multiple(self, tmp_db):
        """记录多条封禁事件，验证数量正确。"""
        for i in range(10):
            event = BanEvent(
                ip=f"192.0.2.{i}",
                jail="sshd",
                action=BanAction.BAN,
                timestamp=datetime(2026, 7, 1, 12, 0, i),
            )
            tmp_db.record_ban(event)

        history = tmp_db.get_ban_history(days=365)
        assert len(history) == 10

    def test_record_unban(self, tmp_db):
        """记录解封事件，验证 action 字段正确。"""
        event = BanEvent(
            ip="192.0.2.1",
            jail="sshd",
            action=BanAction.UNBAN,
            timestamp=datetime(2026, 7, 1, 12, 0, 0),
        )
        tmp_db.record_ban(event)

        history = tmp_db.get_ban_history(days=365)
        assert len(history) == 1
        assert history[0].action == BanAction.UNBAN

    def test_matches_truncation(self, tmp_db):
        """测试 matches 字段超过 500 字符时被截断。"""
        long_matches = "x" * 600
        event = BanEvent(
            ip="192.0.2.1",
            jail="sshd",
            action=BanAction.BAN,
            matches=long_matches,
            timestamp=datetime(2026, 7, 1, 12, 0, 0),
        )
        tmp_db.record_ban(event)

        history = tmp_db.get_ban_history(days=365)
        assert len(history[0].matches) <= 500


class TestBanHistory:
    """封禁历史查询测试"""

    def test_get_history_days_filter(self, tmp_db):
        """测试按天数过滤历史记录。"""
        # 记录一条 30 天前的事件
        old_event = BanEvent(
            ip="10.0.0.1",
            jail="sshd",
            action=BanAction.BAN,
            timestamp=datetime.now() - timedelta(days=30),
        )
        # 记录一条今天的事件
        new_event = BanEvent(
            ip="10.0.0.2",
            jail="sshd",
            action=BanAction.BAN,
            timestamp=datetime.now(),
        )
        tmp_db.record_ban(old_event)
        tmp_db.record_ban(new_event)

        # 查询最近 7 天，应该只有新事件
        history_7 = tmp_db.get_ban_history(days=7)
        assert len(history_7) == 1
        assert history_7[0].ip == "10.0.0.2"

        # 查询最近 60 天，两条都有
        history_60 = tmp_db.get_ban_history(days=60)
        assert len(history_60) == 2

    def test_get_history_empty(self, tmp_db):
        """空数据库查询不应报错。"""
        history = tmp_db.get_ban_history(days=365)
        assert history == []

    def test_get_history_desc_order(self, tmp_db):
        """历史记录按时间倒序排列。"""
        for i in range(3):
            event = BanEvent(
                ip=f"10.0.0.{i}",
                jail="sshd",
                action=BanAction.BAN,
                timestamp=datetime(2026, 7, 1, 12, 0, i),
            )
            tmp_db.record_ban(event)

        history = tmp_db.get_ban_history(days=365)
        # 应该是最新的在最前
        assert history[0].ip == "10.0.0.2"
        assert history[1].ip == "10.0.0.1"
        assert history[2].ip == "10.0.0.0"

    def test_mark_notified(self, tmp_db):
        """测试标记已通知功能。"""
        event = BanEvent(
            ip="10.0.0.1",
            jail="sshd",
            action=BanAction.BAN,
            timestamp=datetime.now(),
        )
        tmp_db.record_ban(event)
        unnotified = tmp_db.get_unnotified_bans()
        assert len(unnotified) == 1

        event_id = unnotified[0][0]
        tmp_db.mark_notified(event_id)

        unnotified_after = tmp_db.get_unnotified_bans()
        assert len(unnotified_after) == 0


class TestCurrentBans:
    """当前封禁快照测试"""

    def test_set_and_get_current_bans(self, tmp_db):
        """写入并读取当前封禁快照。"""
        bans = [
            ("192.0.2.1", "sshd"),
            ("192.0.2.2", "sshd"),
            ("203.0.113.1", "nginx-http-auth"),
        ]
        tmp_db.set_current_bans(bans)

        result = tmp_db.get_current_bans()
        assert len(result) == 3
        assert ("192.0.2.1", "sshd") in result
        assert ("203.0.113.1", "nginx-http-auth") in result

    def test_get_current_bans_empty(self, tmp_db):
        """空快照查询不应报错。"""
        bans = tmp_db.get_current_bans()
        assert bans == []

    def test_set_overwrites_previous(self, tmp_db):
        """再次 set 会覆盖之前的快照。"""
        tmp_db.set_current_bans([("192.0.2.1", "sshd")])
        tmp_db.set_current_bans([("192.0.2.2", "sshd")])

        result = tmp_db.get_current_bans()
        assert len(result) == 1
        assert result[0] == ("192.0.2.2", "sshd")

    def test_set_empty_list_clears(self, tmp_db):
        """设置空列表应清空快照。"""
        tmp_db.set_current_bans([("192.0.2.1", "sshd"), ("192.0.2.2", "nginx-http-auth")])
        tmp_db.set_current_bans([])

        result = tmp_db.get_current_bans()
        assert result == []


class TestDailyStats:
    """每日统计测试"""

    def test_update_and_get_daily_stats(self, tmp_db):
        """写入并查询每日统计。"""
        tmp_db.update_daily_stats("2026-07-01", 10, 5, "US")
        tmp_db.update_daily_stats("2026-07-02", 20, 8, "CN")

        stats = tmp_db.get_daily_stats(days=10)
        assert len(stats) == 2

        # 按日期倒序
        assert stats[0].date == "2026-07-02"
        assert stats[0].total_bans == 20
        assert stats[0].unique_ips == 8
        assert stats[0].top_country == "CN"

    def test_upsert_overwrites(self, tmp_db):
        """upsert 行为：同一日期再次写入应更新数据。"""
        tmp_db.update_daily_stats("2026-07-01", 10, 5, "US")
        tmp_db.update_daily_stats("2026-07-01", 15, 7, "CN")

        stats = tmp_db.get_daily_stats(days=10)
        assert len(stats) == 1
        assert stats[0].total_bans == 15
        assert stats[0].unique_ips == 7
        assert stats[0].top_country == "CN"

    def test_get_daily_stats_days_filter(self, tmp_db):
        """按天数过滤统计。"""
        # 获取昨天的日期
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

        tmp_db.update_daily_stats(yesterday, 10, 5, "US")
        tmp_db.update_daily_stats(old_date, 20, 8, "CN")

        # 查询最近 7 天，应该只有昨天的
        stats = tmp_db.get_daily_stats(days=7)
        assert len(stats) == 1
        assert stats[0].date == yesterday

    def test_get_daily_stats_empty(self, tmp_db):
        """空统计查询。"""
        stats = tmp_db.get_daily_stats(days=30)
        assert stats == []


class TestCountBansToday:
    """今日封禁统计测试"""

    def test_count_bans_today(self, tmp_db):
        """统计今天的封禁次数。"""
        today = datetime.now().strftime("%Y-%m-%d")
        for i in range(3):
            event = BanEvent(
                ip=f"10.0.0.{i}",
                jail="sshd",
                action=BanAction.BAN,
                timestamp=datetime.now(),
            )
            tmp_db.record_ban(event)

        # 也记录一个解封事件（不应计入）
        unban = BanEvent(
            ip="10.0.0.1",
            jail="sshd",
            action=BanAction.UNBAN,
            timestamp=datetime.now(),
        )
        tmp_db.record_ban(unban)

        count = tmp_db.count_bans_today()
        assert count == 3

    def test_count_bans_today_empty(self, tmp_db):
        """空表情况下为 0。"""
        assert tmp_db.count_bans_today() == 0


class TestTopBannedIPs:
    """封禁 IP 排行榜测试"""

    def test_top_banned_ips(self, tmp_db):
        """测试排名逻辑正确。"""
        # IP 10.0.0.1 被 ban 3 次
        for _ in range(3):
            tmp_db.record_ban(BanEvent(
                ip="10.0.0.1", jail="sshd",
                action=BanAction.BAN, timestamp=datetime.now(),
            ))
        # IP 10.0.0.2 被 ban 5 次
        for _ in range(5):
            tmp_db.record_ban(BanEvent(
                ip="10.0.0.2", jail="sshd",
                action=BanAction.BAN, timestamp=datetime.now(),
            ))
        # IP 10.0.0.3 被 ban 1 次
        tmp_db.record_ban(BanEvent(
            ip="10.0.0.3", jail="sshd",
            action=BanAction.BAN, timestamp=datetime.now(),
        ))

        top = tmp_db.top_banned_ips(days=365, limit=10)
        assert len(top) >= 2
        assert top[0] == ("10.0.0.2", 5)
        assert top[1] == ("10.0.0.1", 3)

    def test_top_banned_ips_limit(self, tmp_db):
        """测试 limit 参数限制结果数量。"""
        for i in range(10):
            tmp_db.record_ban(BanEvent(
                ip=f"10.0.0.{i}", jail="sshd",
                action=BanAction.BAN, timestamp=datetime.now(),
            ))

        top = tmp_db.top_banned_ips(days=365, limit=3)
        assert len(top) == 3

    def test_top_banned_ips_empty(self, tmp_db):
        """空数据库返回空列表。"""
        assert tmp_db.top_banned_ips() == []


class TestTopBannedCountries:
    """封禁国家排行榜测试"""

    def test_top_banned_countries(self, tmp_db):
        """测试国家排名正确。"""
        for _ in range(4):
            tmp_db.record_ban(BanEvent(
                ip="1.1.1.1", jail="sshd",
                action=BanAction.BAN, country="US", timestamp=datetime.now(),
            ))
        for _ in range(7):
            tmp_db.record_ban(BanEvent(
                ip="2.2.2.2", jail="sshd",
                action=BanAction.BAN, country="CN", timestamp=datetime.now(),
            ))
        for _ in range(2):
            tmp_db.record_ban(BanEvent(
                ip="3.3.3.3", jail="sshd",
                action=BanAction.BAN, country="RU", timestamp=datetime.now(),
            ))

        top = tmp_db.top_banned_countries(days=365, limit=10)
        assert top[0] == ("CN", 7)
        assert top[1] == ("US", 4)
        assert top[2] == ("RU", 2)

    def test_top_banned_countries_excludes_empty(self, tmp_db):
        """空 country 字段不应参与排名。"""
        for _ in range(3):
            tmp_db.record_ban(BanEvent(
                ip="1.1.1.1", jail="sshd",
                action=BanAction.BAN, country="", timestamp=datetime.now(),
            ))

        top = tmp_db.top_banned_countries(days=365, limit=10)
        assert all(c != "" for c, _ in top)

    def test_top_banned_countries_empty(self, tmp_db):
        """空数据库返回空列表。"""
        assert tmp_db.top_banned_countries() == []


class TestConfigOverride:
    """配置覆盖测试"""

    def test_set_and_get_override(self, tmp_db):
        """设置并读取配置覆盖。"""
        tmp_db.set_config_override("test_key", "test_value")
        val = tmp_db.get_config_override("test_key")
        assert val == "test_value"

    def test_get_override_default(self, tmp_db):
        """不存在的 key 返回默认值。"""
        val = tmp_db.get_config_override("nonexistent", default="fallback")
        assert val == "fallback"

    def test_set_override_overwrites(self, tmp_db):
        """设置同一 key 会覆盖旧值。"""
        tmp_db.set_config_override("key1", "v1")
        tmp_db.set_config_override("key1", "v2")
        assert tmp_db.get_config_override("key1") == "v2"

    def test_delete_override(self, tmp_db):
        """删除后查询应返回默认值。"""
        tmp_db.set_config_override("key1", "v1")
        tmp_db.delete_config_override("key1")
        assert tmp_db.get_config_override("key1", "gone") == "gone"


class TestBoundaryConditions:
    """边界条件测试"""

    def test_large_dataset(self, tmp_db):
        """大量数据写入和查询性能验证。"""
        count = 200
        for i in range(count):
            tmp_db.record_ban(BanEvent(
                ip=f"10.0.{i // 256}.{i % 256}",
                jail=("sshd" if i % 2 == 0 else "nginx-http-auth"),
                action=BanAction.BAN,
                timestamp=datetime.now(),
            ))

        history = tmp_db.get_ban_history(days=365)
        assert len(history) == count

        top_ips = tmp_db.top_banned_ips(days=365, limit=50)
        assert len(top_ips) == 50

    def test_init_is_idempotent(self, tmp_db):
        """init() 多次调用不报错。"""
        tmp_db.init()
        tmp_db.init()
        tmp_db.init()
        # 可以正常插入数据
        tmp_db.record_ban(BanEvent(
            ip="10.0.0.1", jail="sshd",
            action=BanAction.BAN, timestamp=datetime.now(),
        ))
        assert tmp_db.count_bans_today() == 1
