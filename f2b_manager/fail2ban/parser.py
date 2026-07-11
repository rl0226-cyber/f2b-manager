"""
f2b_manager.fail2ban.parser
============================

解析 fail2ban-client 命令输出。

兼容 fail2ban 0.11.x（ASCII 树形字符）和 1.0.x（Unicode 树形字符）两种输出格式。
返回 models.py 中定义的 Fail2banStatus、JailInfo、JailStatus 数据类。
"""

from __future__ import annotations

import re
from typing import Optional

from ..storage.models import Fail2banStatus, JailInfo, JailStatus, ServiceState
from ..utils.logger import get_logger

_logger = get_logger(__name__)


# ──────────────────────────────────────────────
# 测试用的示例输出字符串
# ──────────────────────────────────────────────

# fail2ban 0.11.x 格式
STATUS_OUTPUT_0_11 = """
Status
|- Number of jail:\t2
`- Jail list:\tsshd, nginx-http-auth
"""

# fail2ban 1.0.x 格式
STATUS_OUTPUT_1_0 = """
Status
├─ Number of jail:\t3
└─ Jail list:\tsshd, nginx-http-auth, recidive
"""

# fail2ban 0.11.x 单 jail 详细状态
JAIL_STATUS_OUTPUT_0_11 = """Status for the jail 'sshd'
|- Filter
|  |- Currently failed:\t3
|  |- Total failed:\t156
|  `- Journal matches:\t_SYSTEMD_UNIT=sshd.service + _COMM=sshd
`- Actions
   |- Currently banned:\t5
   |- Total banned:\t42
   `- Banned IP list:\t1.2.3.4 5.6.7.8 9.10.11.12
"""

# fail2ban 1.0.x 单 jail 详细状态
JAIL_STATUS_OUTPUT_1_0 = """Status for the jail 'sshd'
├─ Filter
│  ├─ Currently failed:\t3
│  ├─ Total failed:\t156
│  └─ Journal matches:\t_SYSTEMD_UNIT=sshd.service + _COMM=sshd
└─ Actions
   ├─ Currently banned:\t5
   ├─ Total banned:\t42
   └─ Banned IP list:\t1.2.3.4 5.6.7.8 9.10.11.12
"""

# fail2ban 1.0.x 空封禁 jail
JAIL_STATUS_EMPTY = """Status for the jail 'nginx-http-auth'
├─ Filter
│  ├─ Currently failed:\t0
│  ├─ Total failed:\t3
│  └─ Journal matches:\t_SYSTEMD_UNIT=nginx.service
└─ Actions
   ├─ Currently banned:\t0
   ├─ Total banned:\t0
   └─ Banned IP list:
"""

# fail2ban-client banned 输出示例
BANNED_OUTPUT = """1.2.3.4
5.6.7.8
9.10.11.12"""

# 空封禁列表
BANNED_EMPTY = ""


# ──────────────────────────────────────────────
# 内部工具函数
# ──────────────────────────────────────────────

def _extract_int(line: str) -> int:
    """从形如 '  |- Currently failed:  3' 的行中提取整数值"""
    m = re.search(r":\s*(\d+)", line)
    return int(m.group(1)) if m else 0


def _extract_value(line: str) -> str:
    """从形如 '  `- Jail list:  sshd, nginx' 的行中提取冒号后的值"""
    parts = re.split(r":\s*", line, maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _strip_tree_chars(line: str) -> str:
    """去除 fail2ban 输出的树形字符 (|-  `-  |  ├─ └─ │) 保留文本内容"""
    # 匹配行首的树形字符组合
    cleaned = re.sub(r"^[\s]*[|`├└│\-─]+[\s]*", "", line)
    return cleaned.strip()


def _normalize_lines(raw: str) -> list[str]:
    """将原始输出按行分割，去除空行和首行 'Status'"""
    lines = [line.rstrip() for line in raw.strip().splitlines()]
    return [l for l in lines if l and l.strip() != "Status"]


# ──────────────────────────────────────────────
# 公共解析函数
# ──────────────────────────────────────────────

def parse_version(raw: str) -> str:
    """解析 fail2ban-client version 输出

    Args:
        raw: 命令输出，如 "0.11.2" 或 "Fail2Ban v0.11.2"

    Returns:
        版本号字符串
    """
    raw = raw.strip()
    # 兼容 "Fail2Ban v0.11.2" 格式
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", raw)
    if m:
        return m.group(1)
    return raw or "unknown"


def parse_status(raw: str) -> Fail2banStatus:
    """解析 fail2ban-client status 输出

    支持 0.11.x (ASCII) 和 1.0.x (Unicode) 两种格式。

    Args:
        raw: fail2ban-client status 命令的 stdout

    Returns:
        Fail2banStatus
    """
    status = Fail2banStatus()
    lines = _normalize_lines(raw)

    for line in lines:
        # 跳过纯树形字符行
        cleaned = _strip_tree_chars(line)
        if not cleaned:
            continue

        if "Number of jail" in cleaned:
            status.jail_count = _extract_int(line)
        elif "Jail list" in cleaned:
            raw_jails = _extract_value(line)
            if raw_jails:
                # 用逗号分隔，去除空项
                jail_names = [j.strip() for j in raw_jails.split(",") if j.strip()]
                # 仅用于日志跟踪，实际 jail 列表由 get_jails() 提供
        elif "Currently banned" in cleaned:
            status.total_bans = _extract_int(line)

    _logger.debug("Parsed status: jail_count=%d, total_bans=%d",
                   status.jail_count, status.total_bans)
    return status


def parse_jail_status(raw: str) -> JailStatus:
    """解析 fail2ban-client status <jail> 输出

    支持 0.11.x 和 1.0.x 两种格式。
    提取 jail 名称、封禁数、失败次数、配置参数、封禁 IP 列表。

    Args:
        raw: fail2ban-client status <jail> 命令的 stdout

    Returns:
        JailStatus
    """
    # 提取 jail 名称
    jail_name = ""
    m = re.search(r"Status for the jail ['\"]?([^'\"]+)['\"]?", raw)
    if m:
        jail_name = m.group(1)

    jail_status = JailStatus(name=jail_name, enabled=True)
    lines = _normalize_lines(raw)

    for line in lines:
        cleaned = _strip_tree_chars(line)
        if not cleaned:
            continue

        if "Currently failed" in cleaned:
            jail_status.total_failed = _extract_int(line)
        elif "Total failed" in cleaned:
            jail_status.total_failed = _extract_int(line)
        elif "Currently banned" in cleaned:
            jail_status.current_ban = _extract_int(line)
        elif "Total banned" in cleaned:
            jail_status.total_banned = _extract_int(line)
        elif "Banned IP list" in cleaned:
            raw_ips = _extract_value(line)
            if raw_ips:
                jail_status.banned_ips = raw_ips.split()
        elif "File list" in cleaned or "Journal matches" in cleaned:
            # 跳过文件/日志路径信息
            pass

    _logger.debug("Parsed jail status: name=%s bans=%d failed=%d ips=%d",
                   jail_name, jail_status.current_ban,
                   jail_status.total_failed, len(jail_status.banned_ips))
    return jail_status


def parse_banned_ips(raw: str) -> list[str]:
    """解析 fail2ban-client banned 输出

    Args:
        raw: fail2ban-client banned 命令的 stdout，
             每行一个 IP，空输出表示无封禁

    Returns:
        IP 地址列表
    """
    if not raw or not raw.strip():
        return []
    return [ip.strip() for ip in raw.strip().splitlines() if ip.strip()]


def parse_jail_list(raw: str) -> list[JailInfo]:
    """从 fail2ban-client status 输出中提取 jail 列表

    Args:
        raw: fail2ban-client status 命令的 stdout

    Returns:
        JailInfo 列表（仅 name 和 enabled 字段填充）
    """
    jails: list[JailInfo] = []
    lines = _normalize_lines(raw)

    for line in lines:
        if "Jail list" in line:
            raw_jails = _extract_value(line)
            if raw_jails:
                names = [j.strip() for j in raw_jails.split(",") if j.strip()]
                jails = [JailInfo(name=n, enabled=True) for n in names]
            break

    return jails


# ──────────────────────────────────────────────
# 自测（直接运行本文件时执行）
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=== 测试 parse_version ===")
    assert parse_version("0.11.2") == "0.11.2"
    assert parse_version("Fail2Ban v1.0.2") == "1.0.2"
    assert parse_version("1.0.2\n") == "1.0.2"
    print("  parse_version: PASS")

    print("\n=== 测试 parse_status (0.11.x) ===")
    s = parse_status(STATUS_OUTPUT_0_11)
    assert s.jail_count == 2
    assert s.total_bans == 0  # status 不包含 total_bans
    print(f"  jail_count={s.jail_count}, total_bans={s.total_bans}: PASS")

    print("\n=== 测试 parse_status (1.0.x) ===")
    s = parse_status(STATUS_OUTPUT_1_0)
    assert s.jail_count == 3
    print(f"  jail_count={s.jail_count}: PASS")

    print("\n=== 测试 parse_jail_list (0.11.x) ===")
    jails = parse_jail_list(STATUS_OUTPUT_0_11)
    assert len(jails) == 2
    assert jails[0].name == "sshd"
    assert jails[1].name == "nginx-http-auth"
    print(f"  jails={[j.name for j in jails]}: PASS")

    print("\n=== 测试 parse_jail_status (0.11.x) ===")
    js = parse_jail_status(JAIL_STATUS_OUTPUT_0_11)
    assert js.name == "sshd"
    assert js.total_failed == 156
    assert js.current_ban == 5
    assert js.total_banned == 42
    assert len(js.banned_ips) == 3
    assert "1.2.3.4" in js.banned_ips
    print(f"  name={js.name}, failed={js.total_failed}, "
          f"current_ban={js.current_ban}, total_banned={js.total_banned}, "
          f"ips={js.banned_ips}: PASS")

    print("\n=== 测试 parse_jail_status (1.0.x) ===")
    js = parse_jail_status(JAIL_STATUS_OUTPUT_1_0)
    assert js.name == "sshd"
    assert js.total_failed == 156
    assert js.current_ban == 5
    assert len(js.banned_ips) == 3
    print(f"  name={js.name}: PASS")

    print("\n=== 测试 parse_jail_status (empty) ===")
    js = parse_jail_status(JAIL_STATUS_EMPTY)
    assert js.name == "nginx-http-auth"
    assert js.current_ban == 0
    assert js.total_banned == 0
    assert js.banned_ips == []
    print(f"  name={js.name}, bans=0, ips=[]: PASS")

    print("\n=== 测试 parse_banned_ips ===")
    ips = parse_banned_ips(BANNED_OUTPUT)
    assert len(ips) == 3
    assert "1.2.3.4" in ips
    print(f"  ips={ips}: PASS")

    print("\n=== 测试 parse_banned_ips (empty) ===")
    ips = parse_banned_ips(BANNED_EMPTY)
    assert ips == []
    print("  empty: PASS")

    print("\n✅ 所有测试通过！")
