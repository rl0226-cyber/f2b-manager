"""
f2b_manager.monitor.health
===========================

Fail2ban 健康检查与自动恢复。

定期检查 fail2ban 服务状态:
1. 执行 fail2ban-client ping 验证服务响应
2. 检查 systemd 服务状态
3. 异常时自动重启（最多 3 次），超出上限后仅报警
4. 通过 Telegram Bot 发送健康告警通知
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Optional

from ..config import AppConfig
from ..storage.models import IMessageSender
from ..utils.logger import get_logger

logger = get_logger("monitor.health")


class HealthChecker:
    """Fail2ban 健康检查器。

    核心逻辑:
        check() → ping_fail2ban
            ↓ 成功 → 重置重试计数 → 返回 True
            ↓ 失败
        check_systemd_status()
            ↓ 未达上限 → restart_fail2ban() → 等待 3 秒 → 再 ping
            ↓ 达上限 → 仅发送告警 → 返回 False

    构造函数接收:
        config: 应用全局配置（用于读取 health_alert 开关）
        bot: 消息发送接口（可为 None，此时仅记录日志）

    Usage:
        checker = HealthChecker(config, bot)
        ok = await checker.check()           # 执行一次健康检查
        print(checker.restart_count)         # 当前重试次数
        checker.reset_restart_count()        # 手动重置
    """

    # 最大自动重启次数，超过后停止重试仅报警
    MAX_RESTART_ATTEMPTS = 3

    # 重启后等待服务稳定的秒数
    RESTART_STABILIZE_SECONDS = 3

    def __init__(
        self,
        config: AppConfig,
        bot: Optional[IMessageSender] = None,
    ):
        self._config = config
        self._bot = bot

        # 累计重启次数（服务恢复后重置）
        self._restart_count = 0

    # ── 公共方法 ──────────────────────────────

    async def check(self) -> bool:
        """执行一次完整的健康检查。

        流程:
        1. ping fail2ban → 成功则重置计数返回 True
        2. 检查 systemd 服务状态
        3. 若未超重试上限 → 执行 systemctl restart fail2ban
        4. 等待稳定 → 再 ping 验证
        5. 发送相应的告警通知

        Returns:
            True 表示服务健康或自动恢复成功。
            False 表示异常且本次未恢复。
        """
        # 步骤1: ping 检查
        if self._ping_fail2ban():
            if self._restart_count > 0:
                logger.info(
                    "fail2ban 服务已恢复（之前累计重试 %d 次）",
                    self._restart_count,
                )
            self._restart_count = 0
            return True

        # 步骤2: 服务异常
        logger.warning("fail2ban 服务异常（ping 失败）")

        # 步骤3: 查询 systemd 状态
        systemd_status = self._check_systemd_status()
        logger.info("systemd fail2ban 服务状态: %s", systemd_status)

        # 步骤4: 判断是否继续重试
        if self._restart_count >= self.MAX_RESTART_ATTEMPTS:
            # 超过重试上限，只通知不重试
            logger.error(
                "fail2ban 自动恢复已达上限（%d 次），停止重试",
                self.MAX_RESTART_ATTEMPTS,
            )
            await self._send_alert(
                "\U0001f6a8 <b>Fail2ban \u81ea\u52a8\u6062\u590d\u5931\u8d25</b>\n\n"
                f"\u5df2\u5c1d\u8bd5\u91cd\u542f {self.MAX_RESTART_ATTEMPTS} \u6b21\uff0c\u5747\u672a\u6210\u529f\u3002\n\n"
                "\u8bf7\u624b\u52a8\u68c0\u67e5\u4ee5\u4e0b\u5185\u5bb9:\n"
                "  \u2022 <code>systemctl status fail2ban</code>\n"
                "  \u2022 <code>journalctl -u fail2ban -n 50</code>\n"
                "  \u2022 <code>fail2ban-client -v start</code>"
            )
            return False

        # 步骤5: 尝试重启
        attempt = self._restart_count + 1
        logger.info(
            "\u5c1d\u8bd5\u91cd\u542f fail2ban\uff08\u7b2c %d/%d \u6b21\uff09...",
            attempt, self.MAX_RESTART_ATTEMPTS,
        )

        restart_ok = self._restart_fail2ban()
        self._restart_count += 1

        if restart_ok:
            # 等待服务稳定
            await asyncio.sleep(self.RESTART_STABILIZE_SECONDS)

            if self._ping_fail2ban():
                logger.info("fail2ban \u91cd\u542f\u6210\u529f\uff0c\u670d\u52a1\u5df2\u6062\u590d")
                await self._send_alert(
                    "\u2705 <b>Fail2ban \u5df2\u81ea\u52a8\u6062\u590d</b>\n\n"
                    f"\u91cd\u542f\u5c1d\u8bd5: \u7b2c {self._restart_count} \u6b21\n"
                    "\u5f53\u524d\u72b6\u6001: \u8fd0\u884c\u6b63\u5e38"
                )
                self._restart_count = 0
                return True
            else:
                logger.warning(
                    "fail2ban \u91cd\u542f\u540e\u4ecd\u65e0\u6cd5 ping \u901a"
                    "\uff08\u5269\u4f59\u91cd\u8bd5: %d \u6b21\uff09",
                    self.MAX_RESTART_ATTEMPTS - self._restart_count,
                )
                await self._send_alert(
                    "\u26a0\ufe0f <b>Fail2ban \u91cd\u542f\u540e\u4ecd\u5f02\u5e38</b>\n\n"
                    f"\u91cd\u542f\u5c1d\u8bd5: \u7b2c {self._restart_count}/{self.MAX_RESTART_ATTEMPTS} \u6b21\n"
                    "\u5c06\u7ee7\u7eed\u5c1d\u8bd5\u91cd\u542f..."
                )
        else:
            logger.error(
                "fail2ban \u91cd\u542f\u547d\u4ee4\u6267\u884c\u5931\u8d25"
                "\uff08\u5269\u4f59\u91cd\u8bd5: %d \u6b21\uff09",
                self.MAX_RESTART_ATTEMPTS - self._restart_count,
            )
            await self._send_alert(
                "\u274c <b>Fail2ban \u91cd\u542f\u5931\u8d25</b>\n\n"
                f"\u5c1d\u8bd5\u6b21\u6570: \u7b2c {self._restart_count}/{self.MAX_RESTART_ATTEMPTS} \u6b21\n"
                "<code>systemctl restart fail2ban</code> \u547d\u4ee4\u6267\u884c\u5931\u8d25"
            )

        return False

    def reset_restart_count(self) -> None:
        """重置重试计数。

        适用于管理员手动恢复服务后调用，避免下次异常时仍受上限限制。
        """
        self._restart_count = 0
        logger.info("\u91cd\u8bd5\u8ba1\u6570\u5df2\u624b\u52a8\u91cd\u7f6e")

    @property
    def restart_count(self) -> int:
        """当前累计重试次数。"""
        return self._restart_count

    # ── 内部方法 ──────────────────────────────

    def _ping_fail2ban(self) -> bool:
        """执行 fail2ban-client ping，验证服务是否正常响应。

        Returns:
            True 表示服务正常（ping 返回 pong）。
        """
        try:
            result = subprocess.run(
                ["fail2ban-client", "ping"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and "pong" in result.stdout.lower():
                logger.debug("fail2ban ping \u6210\u529f")
                return True
            else:
                logger.debug(
                    "fail2ban ping \u5931\u8d25: rc=%d stdout=%s stderr=%s",
                    result.returncode,
                    result.stdout.strip(),
                    result.stderr.strip(),
                )
                return False
        except FileNotFoundError:
            logger.error("fail2ban-client \u672a\u5b89\u88c5")
            return False
        except subprocess.TimeoutExpired:
            logger.warning("fail2ban-client ping \u8d85\u65f6")
            return False
        except Exception as e:
            logger.error("fail2ban ping \u5f02\u5e38: %s", e)
            return False

    def _check_systemd_status(self) -> str:
        """检查 fail2ban 的 systemd 服务状态。

        Returns:
            人类可读的状态描述字符串。
        """
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "fail2ban"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            status = result.stdout.strip()
            mapping = {
                "active": "active (\u8fd0\u884c\u4e2d)",
                "inactive": "inactive (\u5df2\u505c\u6b62)",
                "failed": "failed (\u542f\u52a8\u5931\u8d25)",
                "activating": "activating (\u542f\u52a8\u4e2d)",
                "deactivating": "deactivating (\u505c\u6b62\u4e2d)",
            }
            return mapping.get(status, f"unknown ({status})")
        except FileNotFoundError:
            return "systemctl \u4e0d\u53ef\u7528\uff08\u975e systemd \u7cfb\u7edf\uff09"
        except Exception as e:
            logger.warning("\u68c0\u67e5 systemd \u72b6\u6001\u5931\u8d25: %s", e)
            return f"\u67e5\u8be2\u5931\u8d25: {e}"

    def _restart_fail2ban(self) -> bool:
        """通过 systemctl 重启 fail2ban 服务。

        Returns:
            True 表示 systemctl restart 命令执行成功（返回码 0）。
        """
        try:
            result = subprocess.run(
                ["systemctl", "restart", "fail2ban"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                logger.info("fail2ban \u91cd\u542f\u6210\u529f")
                return True
            else:
                logger.error(
                    "fail2ban \u91cd\u542f\u5931\u8d25: rc=%d stderr=%s",
                    result.returncode,
                    result.stderr.strip(),
                )
                return False
        except FileNotFoundError:
            logger.error("systemctl \u4e0d\u53ef\u7528\uff0c\u65e0\u6cd5\u91cd\u542f")
            return False
        except subprocess.TimeoutExpired:
            logger.error("systemctl restart \u8d85\u65f6")
            return False
        except Exception as e:
            logger.error("\u91cd\u542f fail2ban \u5f02\u5e38: %s", e)
            return False

    async def _send_alert(self, message: str) -> None:
        """发送健康检查告警消息。

        发送前检查:
        - notify.enable_health_alert 开关
        - bot 和 notify_chat_id 是否可用
        """
        if not self._config.notify.enable_health_alert:
            logger.debug("\u5065\u5eb7\u68c0\u67e5\u901a\u77e5\u5df2\u5173\u95ed")
            return

        if self._bot is None:
            logger.debug("bot \u672a\u914d\u7f6e\uff0c\u8df3\u8fc7\u53d1\u9001\u5065\u5eb7\u68c0\u67e5\u544a\u8b66")
            return

        chat_id = self._config.telegram.notify_chat_id
        if chat_id == 0:
            logger.warning("notify_chat_id \u672a\u8bbe\u7f6e\uff0c\u65e0\u6cd5\u53d1\u9001\u5065\u5eb7\u68c0\u67e5\u544a\u8b66")
            return

        try:
            await self._bot.send_alert(
                chat_id=chat_id,
                message=message,
                parse_mode="HTML",
            )
            logger.info("\u5df2\u53d1\u9001\u5065\u5eb7\u68c0\u67e5\u544a\u8b66")
        except Exception as e:
            logger.error("\u53d1\u9001\u5065\u5eb7\u68c0\u67e5\u544a\u8b66\u5931\u8d25: %s", e)
