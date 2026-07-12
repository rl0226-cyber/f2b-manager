"""
f2b_manager.fail2ban.manager
=============================

Fail2ban 运行时管理器。

实现 IFail2banManager 接口，通过 run_command() 调用 fail2ban-client
获取/修改 fail2ban 运行状态。所有方法都有完善的错误处理和日志记录。

注意：本模块不会在导入时检查 fail2ban 是否可用，只在调用时检查。
在无 fail2ban 的环境（如 macOS）中导入不会崩溃，调用方法时会抛出异常。
"""

from __future__ import annotations

import datetime
import subprocess
from typing import Optional

from ..storage.models import (
    Fail2banStatus,
    JailInfo,
    JailStatus,
    ServiceState,
)
from ..utils.shell import run_command, which
from ..utils.logger import get_logger
from .parser import (
    parse_status,
    parse_jail_status,
    parse_banned_ips,
    parse_jail_list,
    parse_version,
)

_logger = get_logger(__name__)

# fail2ban-client 命令路径
_F2B_CLIENT = "fail2ban-client"


def _get_service_uptime(service: str) -> str:
    """获取 systemd 服务的运行时长。

    Args:
        service: systemd 服务名

    Returns:
        人类可读的运行时长字符串（如 "2h 30m"），获取失败返回空字符串
    """
    try:
        r = subprocess.run(
            ["systemctl", "show", service, "--property=ActiveEnterTimestamp"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return ""

        # 格式: ActiveEnterTimestamp=Sun 2026-07-12 01:06:55 CST
        line = r.stdout.strip()
        if "=" not in line:
            return ""
        ts_str = line.split("=", 1)[1].strip()

        # 解析时间戳
        # systemd 输出格式: "Day YYYY-MM-DD HH:MM:SS TZ"
        # 或 "YYYY-MM-DD HH:MM:SS TZ"
        try:
            # 尝试多种格式
            for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %Z"):
                try:
                    start = datetime.datetime.strptime(ts_str, fmt)
                    # systemd 返回的是本地时间，我们需要把它转成 UTC 或直接用
                    # 但 strptime 默认创建 naive datetime，需要处理
                    now = datetime.datetime.now()
                    delta = now - start
                    break
                except ValueError:
                    continue
            else:
                return ""

            # 格式化为人类可读
            if delta.days > 0:
                return f"{delta.days}d {delta.seconds // 3600}h"
            hours = delta.seconds // 3600
            mins = (delta.seconds % 3600) // 60
            if hours > 0:
                return f"{hours}h {mins}m"
            return f"{mins}m"
        except Exception:
            return ""
    except Exception:
        return ""


class Fail2banNotAvailableError(RuntimeError):
    """fail2ban-client 不可用时抛出"""

    def __init__(self, msg: str = "fail2ban-client 未安装或不可用"):
        super().__init__(msg)


class Fail2banManager:
    """Fail2ban 运行时管理。

    通过调用 fail2ban-client 命令完成所有操作。

    Usage:
        mgr = Fail2banManager()
        status = mgr.get_status()
        jails = mgr.get_jails()
        detail = mgr.get_jail_status("sshd")
    """

    def __init__(self, client_path: Optional[str] = None):
        """初始化管理器。

        Args:
            client_path: fail2ban-client 路径，默认自动检测
        """
        self._client = client_path or _F2B_CLIENT

    # ── 内部方法 ──────────────────────────────

    def _run(self, *args: str, timeout: int = 30) -> str:
        """执行 fail2ban-client 命令并返回 stdout。

        Args:
            *args: 命令参数
            timeout: 超时秒数

        Returns:
            命令的 stdout

        Raises:
            Fail2banNotAvailableError: fail2ban-client 不可用
            subprocess.CalledProcessError: 命令执行失败
        """
        cmd = [self._client, *args]
        _logger.debug("执行命令: %s", " ".join(cmd))
        result = run_command(cmd, timeout=timeout, check=False)

        if not result.success:
            # 检查是否是 fail2ban-client 不存在
            if "not found" in result.stderr.lower() or \
               "no such file" in result.stderr.lower():
                raise Fail2banNotAvailableError(
                    f"fail2ban-client 未安装: {result.stderr}"
                )
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result.stdout

    def _verify_available(self) -> None:
        """验证 fail2ban-client 是否可用。

        Raises:
            Fail2banNotAvailableError: 不可用时抛出
        """
        path = which(self._client)
        if path is None:
            raise Fail2banNotAvailableError(
                f"未找到 {self._client}，请确认 fail2ban 已安装"
            )

    # ── IFail2banManager 接口实现 ─────────────

    def get_status(self) -> Fail2banStatus:
        """获取 fail2ban 整体状态。

        执行 fail2ban-client version + status + banned 三个命令，
        聚合为 Fail2banStatus。

        Returns:
            Fail2banStatus: 版本、运行状态、jail 数量、总封禁数

        Raises:
            Fail2banNotAvailableError: fail2ban-client 不可用
        """
        self._verify_available()
        status = Fail2banStatus()

        try:
            # 1. 获取版本号
            version_output = self._run("version")
            status.version = parse_version(version_output)
        except Exception as e:
            _logger.warning("获取 fail2ban 版本失败: %s", e)
            status.version = "unknown"

        try:
            # 2. 获取服务状态（通过 ping 判断）
            self._run("ping")
            status.state = ServiceState.RUNNING
        except Exception:
            _logger.warning("fail2ban 服务可能未运行")
            status.state = ServiceState.STOPPED

        # 2a. 获取运行时长
        if status.state == ServiceState.RUNNING:
            status.uptime = _get_service_uptime("fail2ban")

        try:
            # 3. 解析 status 输出获取 jail 数量和基本信息
            raw_status = self._run("status")
            parsed = parse_status(raw_status)
            status.jail_count = parsed.jail_count
            status.total_bans = parsed.total_bans
        except Exception as e:
            _logger.warning("获取 fail2ban status 失败: %s", e)

        # 4. 如果 total_bans 未从 status 获取到，尝试通过 banned 命令获取
        if status.total_bans == 0 and status.state == ServiceState.RUNNING:
            try:
                ips = self.get_banned_ips()
                status.total_bans = len(ips)
            except Exception as e:
                _logger.debug("获取 banned IPs 失败: %s", e)

        _logger.info("Fail2ban 状态: version=%s state=%s jails=%d bans=%d",
                      status.version, status.state.value,
                      status.jail_count, status.total_bans)
        return status

    def get_jails(self) -> list[JailInfo]:
        """获取所有启用的 jail 列表。

        执行 fail2ban-client status，解析 jail 列表。

        Returns:
            JailInfo 列表（仅 name 和 enabled 字段填充）

        Raises:
            Fail2banNotAvailableError: fail2ban-client 不可用
        """
        self._verify_available()
        try:
            raw = self._run("status")
            jails = parse_jail_list(raw)
            _logger.info("获取 jail 列表: %s", [j.name for j in jails])

            # 为每个 jail 补充封禁和失败次数
            enriched: list[JailInfo] = []
            for jail in jails:
                try:
                    js = self.get_jail_status(jail.name)
                    jail.current_ban = js.current_ban
                    jail.total_failed = js.total_failed
                    jail.total_banned = js.total_banned
                except Exception as e:
                    _logger.warning("获取 jail '%s' 状态失败: %s", jail.name, e)
                enriched.append(jail)
            return enriched

        except Exception as e:
            _logger.error("获取 jail 列表失败: %s", e)
            raise

    def get_jail_status(self, jail: str) -> JailStatus:
        """获取指定 jail 的详细状态。

        执行 fail2ban-client status <jail>，解析输出。

        Args:
            jail: jail 名称

        Returns:
            JailStatus: 包含封禁 IP 列表、失败次数等详情

        Raises:
            Fail2banNotAvailableError: fail2ban-client 不可用
            ValueError: jail 名称无效
        """
        self._verify_available()
        if not jail or not jail.strip():
            raise ValueError("jail 名称不能为空")

        try:
            raw = self._run("status", jail)
            status = parse_jail_status(raw)
            _logger.info("Jail '%s' 状态: bans=%d failed=%d ips=%d",
                          jail, status.current_ban,
                          status.total_failed, len(status.banned_ips))
            return status
        except subprocess.CalledProcessError as e:
            _logger.error("获取 jail '%s' 状态失败 (exit=%d): %s",
                          jail, e.returncode, e.stderr)
            raise
        except Exception as e:
            _logger.error("获取 jail '%s' 状态时发生未知错误: %s", jail, e)
            raise

    def get_banned_ips(self) -> list[str]:
        """获取所有 jail 中当前被封禁的 IP 列表。

        执行 fail2ban-client banned。

        Returns:
            IP 地址列表

        Raises:
            Fail2banNotAvailableError: fail2ban-client 不可用
        """
        self._verify_available()
        try:
            raw = self._run("banned")
            ips = parse_banned_ips(raw)
            _logger.info("获取封禁 IP 列表: %d 个 IP", len(ips))
            return ips
        except Exception as e:
            _logger.error("获取封禁 IP 列表失败: %s", e)
            raise

    def ban_ip(self, ip: str, jail: str = "sshd") -> bool:
        """手动封禁 IP。

        执行 fail2ban-client set <jail> banip <ip>。

        Args:
            ip: 要封禁的 IP 地址
            jail: 目标 jail 名称，默认 sshd

        Returns:
            操作是否成功

        Raises:
            Fail2banNotAvailableError: fail2ban-client 不可用
            ValueError: IP 地址或 jail 名称无效
        """
        self._verify_available()
        if not ip or not ip.strip():
            raise ValueError("IP 地址不能为空")
        if not jail or not jail.strip():
            raise ValueError("jail 名称不能为空")

        try:
            self._run("set", jail, "banip", ip)
            _logger.info("已手动封禁 IP: %s (jail=%s)", ip, jail)
            return True
        except Exception as e:
            _logger.error("封禁 IP '%s' 失败 (jail=%s): %s", ip, jail, e)
            return False

    def unban_ip(self, ip: str) -> bool:
        """解封 IP。

        执行 fail2ban-client unban <ip>。

        Args:
            ip: 要解封的 IP 地址

        Returns:
            操作是否成功

        Raises:
            Fail2banNotAvailableError: fail2ban-client 不可用
            ValueError: IP 地址无效
        """
        self._verify_available()
        if not ip or not ip.strip():
            raise ValueError("IP 地址不能为空")

        try:
            self._run("unban", ip)
            _logger.info("已解封 IP: %s", ip)
            return True
        except Exception as e:
            _logger.error("解封 IP '%s' 失败: %s", ip, e)
            return False

    def reload(self) -> bool:
        """重载 fail2ban 配置。

        执行 fail2ban-client reload。

        Returns:
            操作是否成功

        Raises:
            Fail2banNotAvailableError: fail2ban-client 不可用
        """
        self._verify_available()
        try:
            self._run("reload", timeout=60)
            _logger.info("fail2ban 配置已重载")
            return True
        except Exception as e:
            _logger.error("重载 fail2ban 配置失败: %s", e)
            return False


# ──────────────────────────────────────────────
# 自测（需要 fail2ban 环境，仅做导入检查）
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Fail2banManager 导入测试 ===")
    mgr = Fail2banManager()
    print(f"实例化成功: {mgr}")

    try:
        status = mgr.get_status()
        print(f"状态: {status}")
    except Fail2banNotAvailableError:
        print("fail2ban 不可用（预期行为，非 Linux 环境或未安装）")
        print("✅ 导入无崩溃，仅在调用时报错，符合预期")
