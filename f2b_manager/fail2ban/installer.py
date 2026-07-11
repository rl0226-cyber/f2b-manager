"""
f2b_manager.fail2ban.installer
===============================

Fail2ban 安装/卸载/更新器。

实现 IFail2banInstaller 接口，负责 fail2ban 的完整生命周期管理：
- 安装：检测发行版 → 包管理器安装 → 配置生成 → action 部署 → systemd 启用
- 卸载：停止服务 → 禁用 → 移除包 → 备份配置（可选）
- 更新：记录旧版本 → 包升级 → 重启 → 记录新版本

所有方法都有完善的错误处理和日志记录。
"""

from __future__ import annotations

import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from ..config import Fail2banConfig
from ..storage.models import InstallResult, DistroInfo
from ..utils.distro import (
    detect_distro,
    get_install_command,
    get_remove_command,
    get_upgrade_command,
    PackageManager,
)
from ..utils.shell import run_command, which
from ..utils.logger import get_logger
from .config_builder import JailConfigBuilder

_logger = get_logger(__name__)

# 部署路径常量
_FAIL2BAN_ACTION_DIR = "/etc/fail2ban/action.d"
_FAIL2BAN_JAIL_LOCAL = "/etc/fail2ban/jail.local"
_FAIL2BAN_CONFIG_DIR = "/etc/fail2ban"
_NOTIFY_SCRIPT_PATH = "/usr/local/bin/f2b-notify.sh"
_PACKAGE_NAME = "fail2ban"


class InstallError(RuntimeError):
    """安装/卸载/更新失败时抛出"""
    pass


class Fail2banInstaller:
    """Fail2ban 安装器。

    Usage:
        cfg = Fail2banConfig(...)
        installer = Fail2banInstaller(cfg)
        result = installer.install()
    """

    # 部署时需要的目录列表
    _REQUIRED_DIRS = [
        _FAIL2BAN_ACTION_DIR,
        _FAIL2BAN_CONFIG_DIR,
        Path(_NOTIFY_SCRIPT_PATH).parent,
    ]

    def __init__(self, config: Fail2banConfig):
        self._config = config
        self._builder = JailConfigBuilder(config)
        self._distro_info: DistroInfo | None = None

    # ── 内部工具方法 ──────────────────────────

    def _get_distro(self) -> DistroInfo:
        """获取发行版信息（带缓存）"""
        if self._distro_info is None:
            self._distro_info = detect_distro()
            _logger.info("检测到发行版: distro=%s version=%s pkg=%s",
                          self._distro_info.distro.value,
                          self._distro_info.version,
                          self._distro_info.package_manager.value)
        return self._distro_info

    def _is_installed(self) -> bool:
        """检查 fail2ban 是否已安装"""
        # 检查 fail2ban-server 和 fail2ban-client 是否都存在
        server = which("fail2ban-server")
        client = which("fail2ban-client")
        return server is not None and client is not None

    def _get_f2b_version(self) -> str:
        """获取当前安装的 fail2ban 版本号"""
        try:
            result = run_command("fail2ban-client version", timeout=10, check=False)
            if result.success:
                from .parser import parse_version
                return parse_version(result.stdout)
        except Exception as e:
            _logger.warning("获取 fail2ban 版本失败: %s", e)
        return "unknown"

    def _run_systemctl(self, action: str, service: str = "fail2ban") -> bool:
        """执行 systemctl 命令。

        Args:
            action: systemctl 动作 (start/stop/enable/disable/restart/daemon-reload)
            service: 服务名

        Returns:
            是否成功
        """
        cmd = f"systemctl {action} {service}"
        _logger.info("执行: %s", cmd)
        result = run_command(cmd, timeout=60, check=False)
        if not result.success:
            _logger.warning("systemctl %s %s 失败: %s", action, service, result.stderr)
        return result.success

    def _ensure_dirs(self) -> None:
        """确保部署所需的目录存在"""
        for d in self._REQUIRED_DIRS:
            try:
                Path(d).mkdir(parents=True, exist_ok=True)
                _logger.debug("目录已就绪: %s", d)
            except (PermissionError, OSError) as e:
                _logger.warning("无法创建目录 %s: %s", d, e)

    def _write_file(self, path: str, content: str, mode: int = 0o644) -> bool:
        """写入文件，自动创建父目录。

        Args:
            path: 文件路径
            content: 文件内容
            mode: 文件权限

        Returns:
            是否成功
        """
        try:
            filepath = Path(path)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")
            filepath.chmod(mode)
            _logger.info("已写入文件: %s (权限 %o)", path, mode)
            return True
        except (PermissionError, OSError) as e:
            _logger.error("写入文件 %s 失败: %s", path, e)
            return False

    def _backup_config(self) -> str:
        """备份 /etc/fail2ban 目录。

        Returns:
            备份目录路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        src = Path(_FAIL2BAN_CONFIG_DIR)
        dst = Path(f"{_FAIL2BAN_CONFIG_DIR}.backup.{timestamp}")

        if not src.exists():
            _logger.info("配置目录 %s 不存在，跳过备份", src)
            return ""

        try:
            shutil.copytree(src, dst, symlinks=True)
            _logger.info("配置已备份到: %s", dst)
            return str(dst)
        except (OSError, shutil.Error) as e:
            _logger.warning("配置备份失败: %s", e)
            return ""

    def _cleanup_f2b_manager_files(self) -> None:
        """清理 f2b-manager 部署的 fail2ban 相关文件"""
        files_to_remove = [
            _FAIL2BAN_JAIL_LOCAL,
            os.path.join(_FAIL2BAN_ACTION_DIR, "telegram-notify.conf"),
        ]
        for f in files_to_remove:
            try:
                path = Path(f)
                if path.exists():
                    path.unlink()
                    _logger.info("已删除: %s", f)
            except OSError as e:
                _logger.warning("删除 %s 失败: %s", f, e)

    # ── IFail2banInstaller 接口实现 ───────────

    def install(self) -> InstallResult:
        """安装 fail2ban。

        完整安装流程：
        1. 检查是否已安装
        2. 检测发行版
        3. 使用包管理器安装 fail2ban
        4. 生成 jail.local
        5. 部署 telegram-notify action 配置
        6. 部署 notify.sh 桥接脚本
        7. systemctl enable --now fail2ban
        8. 验证 fail2ban-client ping

        Returns:
            InstallResult: 安装结果
        """
        start_time = time.monotonic()
        details: list[str] = []

        # 步骤1: 检查是否已安装
        if self._is_installed():
            version = self._get_f2b_version()
            _logger.info("fail2ban 已安装 (版本 %s)，跳过安装", version)
            return InstallResult(
                success=True,
                message=f"fail2ban 已安装 (版本 {version})",
                version=version,
                details=["fail2ban 已安装，跳过"],
                elapsed_seconds=round(time.monotonic() - start_time, 1),
            )

        # 步骤2: 检测发行版
        distro = self._get_distro()
        if distro.package_manager == PackageManager.UNKNOWN:
            return InstallResult(
                success=False,
                message=f"不支持的发行版: {distro.distro.value}",
                details=["无法确定包管理器"],
                elapsed_seconds=round(time.monotonic() - start_time, 1),
            )

        # 步骤3: 安装软件包
        install_cmd = get_install_command(distro.package_manager, _PACKAGE_NAME)
        _logger.info("开始安装 fail2ban: %s", install_cmd)
        details.append(f"发行版: {distro.distro.value} ({distro.version})")
        details.append(f"包管理器: {distro.package_manager.value}")

        result = run_command(install_cmd, timeout=300, check=False)
        if not result.success:
            _logger.error("fail2ban 安装失败: %s", result.stderr)
            return InstallResult(
                success=False,
                message=f"安装失败: {result.stderr[:200]}",
                details=details + [f"错误: {result.stderr}"],
                elapsed_seconds=round(time.monotonic() - start_time, 1),
            )
        details.append("软件包安装成功")

        # 步骤4: 生成并部署 jail.local
        self._ensure_dirs()
        jail_content = self._builder.generate_jail_local()
        if self._write_file(_FAIL2BAN_JAIL_LOCAL, jail_content, mode=0o644):
            details.append(f"jail.local 已部署到 {_FAIL2BAN_JAIL_LOCAL}")
        else:
            details.append("⚠ 部署 jail.local 失败")

        # 步骤5: 部署 telegram-notify action 配置
        action_content = self._builder.generate_telegram_action()
        action_path = os.path.join(_FAIL2BAN_ACTION_DIR, "telegram-notify.conf")
        if self._write_file(action_path, action_content, mode=0o644):
            details.append(f"telegram-notify action 已部署到 {action_path}")
        else:
            details.append("⚠ 部署 telegram-notify action 失败")

        # 步骤6: 部署 notify.sh 桥接脚本
        notify_content = self._builder.generate_notify_script()
        if self._write_file(_NOTIFY_SCRIPT_PATH, notify_content, mode=0o755):
            details.append(f"notify.sh 已部署到 {_NOTIFY_SCRIPT_PATH}")
        else:
            details.append("⚠ 部署 notify.sh 失败")

        # 步骤7: systemctl enable --now
        self._run_systemctl("enable", "fail2ban")
        if self._run_systemctl("start", "fail2ban"):
            details.append("fail2ban 服务已启动并设置为开机自启")
        else:
            # 尝试用 restart 代替 start
            self._run_systemctl("restart", "fail2ban")
            details.append("fail2ban 服务已启用（启动时可能有延迟）")

        # 步骤8: 验证
        version = "unknown"
        try:
            time.sleep(1)  # 等待服务完全启动
            ping = run_command("fail2ban-client ping", timeout=10, check=False)
            if ping.success:
                version = self._get_f2b_version()
                details.append(f"验证成功: fail2ban v{version} 正在运行")
            else:
                details.append("⚠ fail2ban ping 验证失败，请检查日志")
        except Exception as e:
            details.append(f"⚠ 验证时出错: {e}")

        elapsed = round(time.monotonic() - start_time, 1)
        _logger.info("fail2ban 安装完成 (%.1fs)", elapsed)
        return InstallResult(
            success=True,
            message=f"fail2ban v{version} 安装成功",
            version=version,
            details=details,
            elapsed_seconds=elapsed,
        )

    def uninstall(self, keep_config: bool = True) -> InstallResult:
        """卸载 fail2ban。

        卸载流程：
        1. systemctl stop fail2ban
        2. systemctl disable fail2ban
        3. 备份配置（若 keep_config=True）
        4. 使用包管理器卸载
        5. 清理 f2b-manager 部署的配置文件

        Args:
            keep_config: 是否保留配置备份

        Returns:
            InstallResult: 卸载结果
        """
        start_time = time.monotonic()
        details: list[str] = []

        if not self._is_installed():
            _logger.info("fail2ban 未安装，跳过卸载")
            return InstallResult(
                success=True,
                message="fail2ban 未安装",
                details=["fail2ban 未安装，无需卸载"],
                elapsed_seconds=round(time.monotonic() - start_time, 1),
            )

        version = self._get_f2b_version()
        details.append(f"当前版本: {version}")

        # 步骤1+2: 停止并禁用服务
        self._run_systemctl("stop", "fail2ban")
        details.append("fail2ban 服务已停止")
        self._run_systemctl("disable", "fail2ban")
        details.append("fail2ban 开机自启已禁用")

        # 步骤3: 备份配置
        backup_path = ""
        if keep_config:
            backup_path = self._backup_config()
            if backup_path:
                details.append(f"配置已备份到: {backup_path}")
            else:
                details.append("⚠ 配置备份失败或无配置目录")

        # 步骤4: 卸载软件包
        distro = self._get_distro()
        if distro.package_manager != PackageManager.UNKNOWN:
            remove_cmd = get_remove_command(distro.package_manager, _PACKAGE_NAME)
            _logger.info("卸载 fail2ban: %s", remove_cmd)

            result = run_command(remove_cmd, timeout=120, check=False)
            if result.success:
                details.append("软件包卸载成功")
            else:
                details.append(f"⚠ 软件包卸载可能不完整: {result.stderr[:200]}")
        else:
            details.append("⚠ 无法确定包管理器，请手动卸载 fail2ban")

        # 步骤5: 清理 f2b-manager 部署的文件
        self._cleanup_f2b_manager_files()
        details.append("已清理 f2b-manager 部署的配置文件")

        elapsed = round(time.monotonic() - start_time, 1)
        _logger.info("fail2ban 卸载完成 (%.1fs)", elapsed)
        return InstallResult(
            success=True,
            message=f"fail2ban v{version} 已卸载"
            + (f"，配置备份: {backup_path}" if backup_path else ""),
            version="",
            details=details,
            elapsed_seconds=elapsed,
        )

    def update(self) -> InstallResult:
        """更新 fail2ban。

        更新流程：
        1. 记录当前版本
        2. 检查是否已安装
        3. 使用包管理器升级
        4. 重启 fail2ban 服务
        5. 记录新版本

        Returns:
            InstallResult: 更新结果，含版本变化信息
        """
        start_time = time.monotonic()
        details: list[str] = []

        # 步骤1: 记录当前版本
        if not self._is_installed():
            _logger.warning("fail2ban 未安装，无法更新")
            return InstallResult(
                success=False,
                message="fail2ban 未安装，请先安装",
                details=["fail2ban 未安装"],
                elapsed_seconds=round(time.monotonic() - start_time, 1),
            )

        old_version = self._get_f2b_version()
        details.append(f"更新前版本: {old_version}")

        # 步骤2: 检测发行版
        distro = self._get_distro()
        if distro.package_manager == PackageManager.UNKNOWN:
            return InstallResult(
                success=False,
                message=f"不支持的发行版: {distro.distro.value}",
                details=["无法确定包管理器"],
                elapsed_seconds=round(time.monotonic() - start_time, 1),
            )

        # 步骤3: 执行升级
        upgrade_cmd = get_upgrade_command(distro.package_manager, _PACKAGE_NAME)
        _logger.info("更新 fail2ban: %s", upgrade_cmd)

        result = run_command(upgrade_cmd, timeout=300, check=False)
        if not result.success:
            _logger.error("fail2ban 更新失败: %s", result.stderr)
            return InstallResult(
                success=False,
                message=f"更新失败: {result.stderr[:200]}",
                details=details + [f"错误: {result.stderr}"],
                elapsed_seconds=round(time.monotonic() - start_time, 1),
            )

        # 步骤4: 重启服务
        self._run_systemctl("restart", "fail2ban")
        details.append("fail2ban 服务已重启")

        # 步骤5: 记录新版本
        new_version = self._get_f2b_version()
        details.append(f"更新后版本: {new_version}")

        if old_version != new_version:
            details.append(f"版本变化: {old_version} → {new_version}")
        else:
            details.append("版本未变化（已是最新）")

        elapsed = round(time.monotonic() - start_time, 1)
        _logger.info("fail2ban 更新完成: %s → %s (%.1fs)",
                      old_version, new_version, elapsed)

        return InstallResult(
            success=True,
            message=f"fail2ban 更新完成: {old_version} → {new_version}",
            version=new_version,
            old_version=old_version,
            details=details,
            elapsed_seconds=elapsed,
        )


# ──────────────────────────────────────────────
# 自测（只做导入检查）
# ──────────────────────────────────────────────

if __name__ == "__main__":
    from ..config import Fail2banConfig

    print("=== Fail2banInstaller 导入测试 ===")
    cfg = Fail2banConfig()
    installer = Fail2banInstaller(cfg)
    print(f"实例化成功: {installer}")

    if installer._is_installed():
        print(f"fail2ban 已安装，版本: {installer._get_f2b_version()}")
    else:
        print("fail2ban 未安装（预期行为，非 Linux 环境）")
        print("✅ 导入无崩溃，符合预期")
