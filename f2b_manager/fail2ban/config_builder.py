"""
f2b_manager.fail2ban.config_builder
====================================

生成 fail2ban jail.local 配置文件。

基于 Fail2banConfig 生成符合 fail2ban 规范的 jail.local 内容，
关键是在每个 jail 的 action 中追加 telegram-notify action。
"""

from __future__ import annotations

import textwrap
from typing import Optional

from ..config import Fail2banConfig
from ..utils.logger import get_logger

_logger = get_logger(__name__)

# 预设 jail 模板（包含常用 jail 的基本配置）
_PRESET_JAILS: dict[str, str] = {
    "sshd": textwrap.dedent("""\
        [sshd]
        enabled = true
        port    = ssh
        logpath = %(sshd_log)s
        backend = %(sshd_backend)s
    """),
    "nginx-http-auth": textwrap.dedent("""\
        [nginx-http-auth]
        enabled  = true
        port     = http,https
        logpath  = %(nginx_error_log)s
    """),
    "nginx-botsearch": textwrap.dedent("""\
        [nginx-botsearch]
        enabled  = true
        port     = http,https
        logpath  = %(nginx_error_log)s
    """),
    "nginx-noscript": textwrap.dedent("""\
        [nginx-noscript]
        enabled  = true
        port     = http,https
        logpath  = %(nginx_error_log)s
    """),
    "recidive": textwrap.dedent("""\
        [recidive]
        enabled  = true
        logpath  = /var/log/fail2ban.log
        bantime  = 1w
        findtime = 1d
        maxretry = 5
    """),
    "proftpd": textwrap.dedent("""\
        [proftpd]
        enabled  = true
        port     = ftp,ftp-data,ftps,ftps-data
        logpath  = %(proftpd_log)s
        backend  = %(proftpd_backend)s
    """),
    "dovecot": textwrap.dedent("""\
        [dovecot]
        enabled  = true
        port     = pop3,pop3s,imap,imaps,submission,465,sieve
        logpath  = %(dovecot_log)s
        backend  = %(dovecot_backend)s
    """),
    "postfix": textwrap.dedent("""\
        [postfix]
        enabled  = true
        mode     = more
        port     = smtp,465,submission
        logpath  = %(postfix_log)s
        backend  = %(postfix_backend)s
    """),
}


class JailConfigBuilder:
    """生成 fail2ban 配置文件。

    基于用户的 Fail2banConfig 和预设模板，生成完整的 jail.local 文件内容。
    关键特性：
    - DEFAULT 段包含全局配置
    - 每个 jail 的 action 中自动追加 telegram-notify
    - 支持递增封禁（incremental banning）
    - 白名单 IP 合并到 ignoreip
    """

    def __init__(self, config: Fail2banConfig):
        self._config = config

    def generate_jail_local(self) -> str:
        """生成完整的 jail.local 配置文件内容。

        包含 [DEFAULT] 段和所有启用的 jail 段。

        Returns:
            jail.local 文件内容字符串
        """
        sections: list[str] = []

        # 1. DEFAULT 段
        sections.append(self._build_default_section())

        # 2. 各 jail 段
        for jail_name in self._config.enabled_jails:
            jail_section = self._build_jail_section(jail_name)
            if jail_section:
                sections.append(jail_section)
            else:
                _logger.warning("未找到预设 jail '%s'，将使用默认配置", jail_name)
                sections.append(self._build_generic_jail(jail_name))

        result = "\n\n".join(sections) + "\n"
        _logger.debug("Generated jail.local with %d sections", len(sections))
        return result

    def _build_default_section(self) -> str:
        """构建 [DEFAULT] 段"""
        cfg = self._config
        lines: list[str] = ["[DEFAULT]"]

        lines.append(f"bantime = {cfg.default_bantime}")
        lines.append(f"findtime = {cfg.default_findtime}")
        lines.append(f"maxretry = {cfg.default_maxretry}")

        # 白名单
        ignoreip = " ".join(cfg.ignoreip)
        lines.append(f"ignoreip = {ignoreip}")

        # banaction
        lines.append("banaction = %(banaction)s")
        # 默认 action（追加 telegram-notify）
        lines.append("action = %(action_)s")

        # 递增封禁
        if cfg.incremental:
            lines.append("")
            lines.append("# 递增封禁: 每次违规封禁时长翻倍")
            lines.append("bantime.increment = true")
            lines.append("bantime.rndtime = 10m")
            lines.append("bantime.factor = 2")
            lines.append(f"bantime.maxtime = {cfg.max_bantime}")

        return "\n".join(lines)

    def _build_jail_section(self, jail_name: str) -> Optional[str]:
        """构建单个 jail 段（基于预设模板）"""
        preset = _PRESET_JAILS.get(jail_name)
        if preset is None:
            return None

        # 追加 telegram-notify action
        action_line = ("action = %(action_)s\n"
                       "         telegram-notify")
        return preset.rstrip() + "\n" + action_line

    def _build_generic_jail(self, jail_name: str) -> str:
        """为没有预设的 jail 生成默认配置"""
        return textwrap.dedent(f"""\
            [{jail_name}]
            enabled = true
            filter  = {jail_name}
            logpath = /var/log/{jail_name}.log
            action  = %(action_)s
                      telegram-notify
        """)

    def generate_telegram_action(self) -> str:
        """生成 /etc/fail2ban/action.d/telegram-notify.conf 内容。

        Returns:
            telegram-notify.conf 内容字符串
        """
        return textwrap.dedent("""\
            # Fail2ban Telegram 通知 Action
            # 当 ban/unban 事件发生时，调用通知脚本
            #
            # 自动生成于 f2b-manager config_builder
            # 部署路径: /etc/fail2ban/action.d/telegram-notify.conf

            [Definition]

            # 服务启动时通知
            actionstart = /usr/local/bin/f2b-notify.sh "start" "<name>"

            # 服务停止时通知
            actionstop = /usr/local/bin/f2b-notify.sh "stop" "<name>"

            # 检查命令（空操作）
            actioncheck =

            # 封禁 IP 时通知 ★关键
            actionban = /usr/local/bin/f2b-notify.sh "ban" "<ip>" "<name>" "<failures>" "<matches>"

            # 解封 IP 时通知
            actionunban = /usr/local/bin/f2b-notify.sh "unban" "<ip>" "<name>"

            # 动作依赖
            actionstart_on_demand = false

            [Init]

            # 通知脚本名称（在 Definition 中硬编码，此处仅作声明）
            name = default
        """)

    def generate_notify_script(self) -> str:
        """生成 /usr/local/bin/f2b-notify.sh 桥接脚本内容。

        Returns:
            notify.sh 内容字符串
        """
        return textwrap.dedent("""\
            #!/bin/bash
            # Fail2ban -> f2b-manager 通知桥接脚本
            # 被 fail2ban action 调用，将事件转发给 f2b-manager
            #
            # 自动生成于 f2b-manager config_builder
            # 部署路径: /usr/local/bin/f2b-notify.sh

            # 参数: $1=事件类型 $2=IP/jail $3=jail $4=failures $5=matches
            EVENT="${1:-unknown}"

            case "$EVENT" in
                ban)
                    # 封禁事件转发
                    f2b-manager notify \\
                        --event "ban" \\
                        --ip "${2:-}" \\
                        --jail "${3:-}" \\
                        --failures "${4:-0}" \\
                        --matches "${5:-}" \\
                        >/dev/null 2>&1 &
                    ;;
                unban)
                    # 解封事件转发
                    f2b-manager notify \\
                        --event "unban" \\
                        --ip "${2:-}" \\
                        --jail "${3:-}" \\
                        >/dev/null 2>&1 &
                    ;;
                start|stop)
                    # 服务启停通知
                    f2b-manager notify \\
                        --event "$EVENT" \\
                        --jail "${2:-}" \\
                        >/dev/null 2>&1 &
                    ;;
                *)
                    ;;
            esac

            exit 0  # 永远返回 0，避免影响 fail2ban 正常工作
        """)


# ──────────────────────────────────────────────
# 自测
# ──────────────────────────────────────────────

if __name__ == "__main__":
    from ..config import Fail2banConfig

    config = Fail2banConfig(
        default_bantime="1h",
        default_findtime="10m",
        default_maxretry=5,
        incremental=True,
        max_bantime="1w",
        ignoreip=["127.0.0.1/8", "::1"],
        enabled_jails=["sshd", "recidive"],
    )

    builder = JailConfigBuilder(config)

    print("=== 生成的 jail.local ===")
    print(builder.generate_jail_local())

    print("\n=== 生成的 telegram-notify.conf ===")
    print(builder.generate_telegram_action())

    print("\n=== 生成的 f2b-notify.sh ===")
    print(builder.generate_notify_script())
