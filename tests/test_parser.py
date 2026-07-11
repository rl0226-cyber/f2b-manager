"""
tests/test_parser.py
====================
fail2ban-client 输出解析器测试。

覆盖: parse_version / parse_status / parse_jail_status / parse_banned_ips / parse_jail_list
兼容: fail2ban 0.11.x (ASCII 树形字符) 和 1.0.x (Unicode 树形字符) 两种格式。
"""
from __future__ import annotations

import pytest

from f2b_manager.fail2ban.parser import (
    parse_version,
    parse_status,
    parse_jail_status,
    parse_banned_ips,
    parse_jail_list,
    _extract_int,
    _extract_value,
    _strip_tree_chars,
    _normalize_lines,
    STATUS_OUTPUT_0_11,
    STATUS_OUTPUT_1_0,
    JAIL_STATUS_OUTPUT_0_11,
    JAIL_STATUS_OUTPUT_1_0,
    JAIL_STATUS_EMPTY,
    BANNED_OUTPUT,
    BANNED_EMPTY,
)
from f2b_manager.storage.models import Fail2banStatus, JailInfo, JailStatus


class TestUtilityFunctions:
    """内部工具函数测试"""

    def test_extract_int(self):
        assert _extract_int("  |- Currently failed:  3") == 3
        assert _extract_int("  |- Currently banned:  0") == 0
        assert _extract_int("  no number here") == 0
        assert _extract_int("") == 0

    def test_extract_value(self):
        assert _extract_value("  `- Jail list:  sshd, nginx") == "sshd, nginx"
        assert _extract_value("no colon here") == ""

    def test_strip_tree_chars_ascii(self):
        assert _strip_tree_chars("  |- Number of jail:  2") == "Number of jail:  2"
        assert _strip_tree_chars("  `- Jail list:  sshd") == "Jail list:  sshd"
        # 嵌套树形字符：外层被剥离，内层保留（parser 按关键词匹配）
        assert _strip_tree_chars("  |  |- Currently failed:  3") == "|- Currently failed:  3"

    def test_strip_tree_chars_unicode(self):
        assert _strip_tree_chars("├─ Number of jail:  3") == "Number of jail:  3"
        assert _strip_tree_chars("└─ Jail list:  sshd, nginx") == "Jail list:  sshd, nginx"
        # 嵌套树形字符：外层被剥离，内层保留
        assert _strip_tree_chars("│  ├─ Currently failed:  3") == "├─ Currently failed:  3"

    def test_normalize_lines(self):
        result = _normalize_lines("Status\nline1\n\nline2\n")
        assert result == ["line1", "line2"]


class TestParseVersion:
    """版本号解析测试"""

    def test_simple_version(self):
        assert parse_version("0.11.2") == "0.11.2"

    def test_with_prefix(self):
        assert parse_version("Fail2Ban v1.0.2") == "1.0.2"

    def test_with_newline(self):
        assert parse_version("1.0.2\n") == "1.0.2"

    def test_two_digit_version(self):
        assert parse_version("0.11") == "0.11"

    def test_no_version(self):
        assert parse_version("unknown") == "unknown"

    def test_empty(self):
        result = parse_version("")
        assert result == "" or result == "unknown"


class TestParseStatus:
    """整体状态解析测试"""

    def test_parse_0_11(self):
        """解析 fail2ban 0.11.x 格式状态输出。"""
        status = parse_status(STATUS_OUTPUT_0_11)
        assert isinstance(status, Fail2banStatus)
        assert status.jail_count == 2

    def test_parse_1_0(self):
        """解析 fail2ban 1.0.x 格式状态输出。"""
        status = parse_status(STATUS_OUTPUT_1_0)
        assert isinstance(status, Fail2banStatus)
        assert status.jail_count == 3

    def test_empty_input(self):
        """空输入不报错。"""
        status = parse_status("")
        assert isinstance(status, Fail2banStatus)
        assert status.jail_count == 0

    def test_status_only_line(self):
        """仅包含 'Status' 行的输入。"""
        status = parse_status("Status\n")
        assert isinstance(status, Fail2banStatus)
        assert status.jail_count == 0


class TestParseJailStatus:
    """单个 jail 详细状态解析测试"""

    def test_parse_0_11(self):
        """解析 0.11.x 格式 jail 状态。"""
        js = parse_jail_status(JAIL_STATUS_OUTPUT_0_11)
        assert js.name == "sshd"
        assert js.total_failed == 156
        assert js.current_ban == 5
        assert js.total_banned == 42
        assert len(js.banned_ips) == 3
        assert "1.2.3.4" in js.banned_ips
        assert "5.6.7.8" in js.banned_ips
        assert "9.10.11.12" in js.banned_ips

    def test_parse_1_0(self):
        """解析 1.0.x 格式 jail 状态。"""
        js = parse_jail_status(JAIL_STATUS_OUTPUT_1_0)
        assert js.name == "sshd"
        assert js.total_failed == 156
        assert js.current_ban == 5
        assert js.total_banned == 42
        assert len(js.banned_ips) == 3

    def test_parse_empty_jail(self):
        """解析无封禁的 jail 状态。"""
        js = parse_jail_status(JAIL_STATUS_EMPTY)
        assert js.name == "nginx-http-auth"
        assert js.current_ban == 0
        assert js.total_banned == 0
        assert js.total_failed == 3
        assert js.banned_ips == []

    def test_jail_name_with_quotes(self):
        """jail 名称带引号。"""
        raw = "Status for the jail 'custom-jail'\n...\n"
        js = parse_jail_status(raw)
        assert js.name == "custom-jail"

    def test_empty_input(self):
        """空输入不报错。"""
        js = parse_jail_status("")
        assert isinstance(js, JailStatus)
        assert js.name == ""
        assert js.banned_ips == []

    def test_enabled_flag(self):
        """解析的 jail 默认 enabled=True。"""
        js = parse_jail_status(JAIL_STATUS_OUTPUT_0_11)
        assert js.enabled is True


class TestParseBannedIPs:
    """封禁 IP 列表解析测试"""

    def test_normal_output(self):
        ips = parse_banned_ips(BANNED_OUTPUT)
        assert len(ips) == 3
        assert "1.2.3.4" in ips
        assert "5.6.7.8" in ips
        assert "9.10.11.12" in ips

    def test_empty_string(self):
        ips = parse_banned_ips(BANNED_EMPTY)
        assert ips == []

    def test_whitespace_only(self):
        ips = parse_banned_ips("  \n  \n  ")
        assert ips == []

    def test_none_input(self):
        ips = parse_banned_ips("")
        assert ips == []

    def test_single_ip(self):
        ips = parse_banned_ips("1.2.3.4")
        assert ips == ["1.2.3.4"]

    def test_ips_with_trailing_whitespace(self):
        ips = parse_banned_ips("  1.2.3.4  \n  5.6.7.8  ")
        assert ips == ["1.2.3.4", "5.6.7.8"]


class TestParseJailList:
    """Jail 列表解析测试"""

    def test_parse_0_11(self):
        jails = parse_jail_list(STATUS_OUTPUT_0_11)
        assert len(jails) == 2
        assert jails[0].name == "sshd"
        assert jails[1].name == "nginx-http-auth"
        assert all(j.enabled for j in jails)

    def test_parse_1_0(self):
        jails = parse_jail_list(STATUS_OUTPUT_1_0)
        assert len(jails) == 3
        assert jails[0].name == "sshd"
        assert jails[1].name == "nginx-http-auth"
        assert jails[2].name == "recidive"

    def test_empty_jail_list(self):
        jails = parse_jail_list("Status\n`- Jail list:\t\n")
        assert jails == []

    def test_empty_input(self):
        jails = parse_jail_list("")
        assert jails == []

    def test_single_jail(self):
        raw = "Status\n├─ Number of jail:\t1\n└─ Jail list:\tsshd"
        jails = parse_jail_list(raw)
        assert len(jails) == 1
        assert jails[0].name == "sshd"


class TestCrossVersionConsistency:
    """跨版本一致性测试：两种格式解析结果应该一致"""

    def test_status_consistency(self):
        """两种版本格式应产生一致的 jail 列表。"""
        jails_0_11 = parse_jail_list(STATUS_OUTPUT_0_11)
        # 1.0 多了 recidive，所以只比较共同部分
        assert jails_0_11[0].name == "sshd"
        assert jails_0_11[1].name == "nginx-http-auth"

    def test_jail_status_consistency(self):
        """两种版本格式应产生一致的 jail 状态。"""
        js_0 = parse_jail_status(JAIL_STATUS_OUTPUT_0_11)
        js_1 = parse_jail_status(JAIL_STATUS_OUTPUT_1_0)

        assert js_0.name == js_1.name == "sshd"
        assert js_0.total_failed == js_1.total_failed == 156
        assert js_0.current_ban == js_1.current_ban == 5
        assert js_0.total_banned == js_1.total_banned == 42
        assert js_0.banned_ips == js_1.banned_ips
