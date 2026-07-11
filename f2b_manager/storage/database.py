"""
f2b_manager.storage.database
============================

SQLite 状态库操作。

负责封禁历史记录、当前封禁快照、每日统计和配置覆盖的持久化。
所有表结构在 init() 时自动创建，支持幂等调用。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import BanAction, BanEvent, DailyStat


# SQL 建表语句
_SCHEMA = """
CREATE TABLE IF NOT EXISTS ban_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ip          TEXT NOT NULL,
    jail        TEXT NOT NULL,
    action      TEXT NOT NULL,
    failures    INTEGER DEFAULT 0,
    country     TEXT DEFAULT '',
    matches     TEXT DEFAULT '',
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    notified    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ban_history_ip
    ON ban_history(ip);
CREATE INDEX IF NOT EXISTS idx_ban_history_timestamp
    ON ban_history(timestamp);

CREATE TABLE IF NOT EXISTS current_bans (
    ip          TEXT NOT NULL,
    jail        TEXT NOT NULL,
    banned_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ip, jail)
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date        TEXT PRIMARY KEY,
    total_bans  INTEGER DEFAULT 0,
    unique_ips  INTEGER DEFAULT 0,
    top_country TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS config_overrides (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class StateDB:
    """SQLite 状态库（线程安全）"""

    def __init__(self, db_path: str = "/var/lib/f2b-manager/state.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()
        self.init()

    def _connect(self) -> None:
        """建立数据库连接"""
        path = Path(self._db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        # 开启 WAL 模式，提升读写并发性能
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def init(self) -> None:
        """初始化表结构（幂等）"""
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        """关闭数据库连接"""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    # ── 封禁历史 ──────────────────────────────

    def record_ban(self, event: BanEvent) -> None:
        """记录封禁/解封事件到历史表"""
        with self._lock:
            self._conn.execute(
                """INSERT INTO ban_history
                   (ip, jail, action, failures, country, matches, timestamp, notified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    event.ip,
                    event.jail,
                    event.action.value,
                    event.failures,
                    event.country,
                    event.matches[:500],  # 限制长度，避免超大日志
                    event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            self._conn.commit()

    def mark_notified(self, event_id: int) -> None:
        """标记某条记录已通知"""
        with self._lock:
            self._conn.execute(
                "UPDATE ban_history SET notified = 1 WHERE id = ?",
                (event_id,),
            )
            self._conn.commit()

    def get_ban_history(self, days: int = 7) -> list[BanEvent]:
        """查询最近 N 天的封禁历史"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM ban_history
                   WHERE timestamp >= ?
                   ORDER BY timestamp DESC""",
                (cutoff,),
            ).fetchall()

        return [
            BanEvent(
                ip=row["ip"],
                jail=row["jail"],
                action=BanAction(row["action"]),
                failures=row["failures"],
                country=row["country"],
                matches=row["matches"],
                timestamp=datetime.strptime(
                    row["timestamp"], "%Y-%m-%d %H:%M:%S"
                ),
            )
            for row in rows
        ]

    def get_unnotified_bans(self) -> list[tuple[int, BanEvent]]:
        """获取尚未通知的封禁记录（轮询兜底用）"""
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM ban_history
                   WHERE notified = 0 AND action = 'ban'
                   ORDER BY timestamp ASC"""
            ).fetchall()

        return [
            (
                row["id"],
                BanEvent(
                    ip=row["ip"],
                    jail=row["jail"],
                    action=BanAction(row["action"]),
                    failures=row["failures"],
                    country=row["country"],
                    matches=row["matches"],
                    timestamp=datetime.strptime(
                        row["timestamp"], "%Y-%m-%d %H:%M:%S"
                    ),
                ),
            )
            for row in rows
        ]

    # ── 当前封禁快照 ──────────────────────────

    def get_current_bans(self) -> list[tuple[str, str]]:
        """获取当前封禁快照 [(ip, jail), ...]"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ip, jail FROM current_bans"
            ).fetchall()
        return [(row["ip"], row["jail"]) for row in rows]

    def set_current_bans(self, bans: list[tuple[str, str]]) -> None:
        """全量更新当前封禁快照"""
        with self._lock:
            self._conn.execute("DELETE FROM current_bans")
            self._conn.executemany(
                "INSERT INTO current_bans (ip, jail) VALUES (?, ?)",
                bans,
            )
            self._conn.commit()

    # ── 每日统计 ──────────────────────────────

    def get_daily_stats(self, days: int = 7) -> list[DailyStat]:
        """查询每日统计"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM daily_stats
                   WHERE date >= ?
                   ORDER BY date DESC""",
                (cutoff,),
            ).fetchall()
        return [
            DailyStat(
                date=row["date"],
                total_bans=row["total_bans"],
                unique_ips=row["unique_ips"],
                top_country=row["top_country"],
            )
            for row in rows
        ]

    def update_daily_stats(self, date: str, total_bans: int,
                           unique_ips: int, top_country: str = "") -> None:
        """更新某日统计（upsert）"""
        with self._lock:
            self._conn.execute(
                """INSERT INTO daily_stats (date, total_bans, unique_ips, top_country)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                       total_bans = excluded.total_bans,
                       unique_ips = excluded.unique_ips,
                       top_country = excluded.top_country""",
                (date, total_bans, unique_ips, top_country),
            )
            self._conn.commit()

    # ── 配置覆盖 ──────────────────────────────

    def set_config_override(self, key: str, value: str) -> None:
        """设置配置覆盖项（upsert）"""
        with self._lock:
            self._conn.execute(
                """INSERT INTO config_overrides (key, value)
                   VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )
            self._conn.commit()

    def get_config_override(self, key: str, default: str = "") -> str:
        """读取配置覆盖项"""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM config_overrides WHERE key = ?",
                (key,),
            ).fetchone()
        return row["value"] if row else default

    def delete_config_override(self, key: str) -> None:
        """删除配置覆盖项"""
        with self._lock:
            self._conn.execute(
                "DELETE FROM config_overrides WHERE key = ?", (key,)
            )
            self._conn.commit()

    # ── 统计查询 ──────────────────────────────

    def count_bans_today(self) -> int:
        """统计今日封禁次数"""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            row = self._conn.execute(
                """SELECT COUNT(*) as cnt FROM ban_history
                   WHERE action = 'ban' AND timestamp LIKE ?""",
                (f"{today}%",),
            ).fetchone()
        return row["cnt"] if row else 0

    def top_banned_ips(self, days: int = 7, limit: int = 10) -> list[tuple[str, int]]:
        """查询封禁次数最多的 IP"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with self._lock:
            rows = self._conn.execute(
                """SELECT ip, COUNT(*) as cnt FROM ban_history
                   WHERE action = 'ban' AND timestamp >= ?
                   GROUP BY ip ORDER BY cnt DESC LIMIT ?""",
                (cutoff, limit),
            ).fetchall()
        return [(row["ip"], row["cnt"]) for row in rows]

    def top_banned_countries(self, days: int = 7,
                             limit: int = 10) -> list[tuple[str, int]]:
        """查询封禁次数最多的国家"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with self._lock:
            rows = self._conn.execute(
                """SELECT country, COUNT(*) as cnt FROM ban_history
                   WHERE action = 'ban' AND timestamp >= ?
                     AND country != ''
                   GROUP BY country ORDER BY cnt DESC LIMIT ?""",
                (cutoff, limit),
            ).fetchall()
        return [(row["country"], row["cnt"]) for row in rows]
