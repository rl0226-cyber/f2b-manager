"""
tests/test_config_builder.py
=============================
jail.local / action / notify 脚本生成测试。

覆盖: DEFAULT 段生成 / jail 段生成 / telegram-notify action /
       notify 脚本 / 递增封禁 / 白名单 / 预设 jail / 自定义 jail。
"""
from __future__ import annotations

import pytest

from f2b_manager.config import Fail2banConfig
from f2b_manager.fail2ban.config_builder import JailConfigBuilder


@pytest.fixture
def builder():
    """标准测试用 builder（开启递增封禁，2 个 jail）。"""
    config = Fail2banConfig(
        default_bantime="1h",
        default_findtime="10m",
        default_maxretry=5,
        incremental=True,
        max_bantime="1w",
        ignoreip=["127.0.0.1/8", "::1"],
        enabled_jails=["sshd", "recidive"],
    )
    return JailConfigBuilder(config)


@pytest.fixture
def builder_no_incremental():
    """关闭递增封禁的 builder。"""
    config = Fail2banConfig(
        default_bantime="30m",
        default_findtime="5m",
        default_maxretry=3,
        incremental=False,
        max_bantime="1w",
        ignoreip=["127.0.0.1/8"],
        enabled_jails=["sshd"],
    )
    return JailConfigBuilder(config)


class TestDefaultSection:
    """[DEFAULT] 段测试"""

    def test_contains_config_values(self, builder):
        """DEFAULT 段包含所有配置值。"""
        output = builder.generate_jail_local()
        assert "[DEFAULT]" in output
        assert "bantime = 1h" in output
        assert "findtime = 10m" in output
        assert "maxretry = 5" in output

    def test_contains_ignoreip(self, builder):
        """DEFAULT 段包含 ignoreip 白名单。"""
        output = builder.generate_jail_local()
        assert "ignoreip = 127.0.0.1/8 ::1" in output

    def test_contains_banaction(self, builder):
        """DEFAULT 段包含 banaction。"""
        output = builder.generate_jail_local()
        assert "banaction = %(banaction)s" in output

    def test_contains_action(self, builder):
        """DEFAULT 段包含 action。"""
        output = builder.generate_jail_local()
        assert "action = %(action_)s" in output

    def test_incremental_bantime_config(self, builder):
        """开启递增封禁时的配置。"""
        output = builder.generate_jail_local()
        assert "bantime.increment = true" in output
        assert "bantime.rndtime = 10m" in output
        assert "bantime.factor = 2" in output
        assert "bantime.maxtime = 1w" in output
        assert "递增封禁" in output

    def test_no_incremental_config(self, builder_no_incremental):
        """关闭递增封禁时不包含相关配置。"""
        output = builder_no_incremental.generate_jail_local()
        assert "bantime.increment" not in output
        assert "bantime.rndtime" not in output


class TestJailSection:
    """Jail 段测试"""

    def test_sshd_jail_present(self, builder):
        """sshd jail 应出现。"""
        output = builder.generate_jail_local()
        assert "[sshd]" in output
        assert "enabled = true" in output
        assert "port    = ssh" in output

    def test_recidive_jail_present(self, builder):
        """recidive jail 应出现。"""
        output = builder.generate_jail_local()
        assert "[recidive]" in output
        assert "bantime  = 1w" in output
        assert "maxretry = 5" in output


class TestTelegramAction:
    """Telegram action 追加测试"""

    def test_action_appended_to_jails(self, builder):
        """每个 jail 后应追加 telegram-notify action。"""
        output = builder.generate_jail_local()
        # 检查 sshd 后有 telegram-notify
        assert "telegram-notify" in output
        # 至少出现 2 次（DEFAULT 的 action 行不算，看 jail section）
        count = output.count("telegram-notify")
        assert count >= 2  # sshd + recidive

    def test_action_format(self, builder):
        """action 行格式正确。"""
        output = builder.generate_jail_local()
        # 应该包含 %(action_)s 和 telegram-notify 的形式
        assert "action = %(action_)s" in output


class TestCustomJail:
    """非预设 jail 测试"""

    def test_generic_jail_generated(self):
        """非预设 jail 生成默认配置。"""
        config = Fail2banConfig(
            enabled_jails=["custom-service"],
        )
        builder = JailConfigBuilder(config)
        output = builder.generate_jail_local()

        assert "[custom-service]" in output
        assert "enabled = true" in output
        assert "filter  = custom-service" in output
        assert "logpath = /var/log/custom-service.log" in output
        assert "telegram-notify" in output


class TestMultipleJails:
    """多 jail 配置测试"""

    def test_enabled_jails_order(self, builder):
        """jail 顺序应与配置一致。"""
        output = builder.generate_jail_local()
        sshd_idx = output.index("[sshd]")
        recidive_idx = output.index("[recidive]")
        assert sshd_idx < recidive_idx

    def test_only_enabled_jails_included(self):
        """只有 enabled_jails 中的 jail 被包含。"""
        config = Fail2banConfig(
            enabled_jails=["proftpd"],
        )
        builder = JailConfigBuilder(config)
        output = builder.generate_jail_local()

        assert "[proftpd]" in output
        assert "[sshd]" not in output  # 未启用
        assert "[recidive]" not in output  # 未启用

    def test_all_preset_jails(self):
        """所有预设 jail 都能生成。"""
        config = Fail2banConfig(
            enabled_jails=[
                "sshd", "nginx-http-auth", "nginx-botsearch",
                "dovecot", "postfix", "proftpd",
            ],
        )
        builder = JailConfigBuilder(config)
        output = builder.generate_jail_local()

        assert "[sshd]" in output
        assert "[nginx-http-auth]" in output
        assert "[nginx-botsearch]" in output
        assert "[dovecot]" in output
        assert "[postfix]" in output
        assert "[proftpd]" in output

    def test_empty_jails(self):
        """空 jail 列表不包含 jail 段。"""
        config = Fail2banConfig(enabled_jails=[])
        builder = JailConfigBuilder(config)
        output = builder.generate_jail_local()

        assert "[DEFAULT]" in output
        # 不应该有其他 jail section
        # 统计 [ 数量
        assert output.count("[") == 1  # 只有 [DEFAULT]


class TestActionConfig:
    """Action 配置文件测试"""

    def test_generate_telegram_action(self, builder):
        """生成 telegram-notify.conf。"""
        action = builder.generate_telegram_action()
        assert "[Definition]" in action
        assert "actionstart" in action
        assert "actionstop" in action
        assert "actionban" in action
        assert "actionunban" in action
        assert "f2b-notify.sh" in action
        assert 'ban"' in action or "\"ban\"" in action
        assert "unban" in action

    def test_action_config_has_init_section(self, builder):
        """action 配置包含 [Init] 段。"""
        action = builder.generate_telegram_action()
        assert "[Init]" in action
        assert "name = default" in action


class TestNotifyScript:
    """通知脚本测试"""

    def test_generate_notify_script(self, builder):
        """生成 f2b-notify.sh。"""
        script = builder.generate_notify_script()
        assert "#!/bin/bash" in script
        assert "f2b-manager notify" in script
        assert "case" in script
        assert "ban" in script
        assert "unban" in script
        assert "start" in script
        assert "stop" in script
        assert "exit 0" in script  # 永远返回 0

    def test_notify_script_has_ban_block(self, builder):
        """脚本包含 ban 事件处理。"""
        script = builder.generate_notify_script()
        assert "--event" in script
        assert "--ip" in script
        assert "--jail" in script
        assert "--failures" in script
        assert "--matches" in script


class TestConfigParams:
    """不同参数的组合测试"""

    def test_different_bantime(self):
        config = Fail2banConfig(default_bantime="24h", enabled_jails=["sshd"])
        builder = JailConfigBuilder(config)
        output = builder.generate_jail_local()
        assert "bantime = 24h" in output

    def test_different_findtime(self):
        config = Fail2banConfig(default_findtime="30m", enabled_jails=["sshd"])
        builder = JailConfigBuilder(config)
        output = builder.generate_jail_local()
        assert "findtime = 30m" in output

    def test_different_maxretry(self):
        config = Fail2banConfig(default_maxretry=10, enabled_jails=["sshd"])
        builder = JailConfigBuilder(config)
        output = builder.generate_jail_local()
        assert "maxretry = 10" in output

    def test_multiple_ignoreip(self):
        config = Fail2banConfig(
            ignoreip=["127.0.0.1/8", "10.0.0.0/8", "192.168.0.0/16"],
            enabled_jails=["sshd"],
        )
        builder = JailConfigBuilder(config)
        output = builder.generate_jail_local()
        assert "127.0.0.1/8" in output
        assert "10.0.0.0/8" in output
        assert "192.168.0.0/16" in output
