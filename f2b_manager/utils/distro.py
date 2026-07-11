"""
f2b_manager.utils.distro
========================

Linux 发行版检测。

读取 /etc/os-release 识别发行版，映射到对应的包管理器。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..storage.models import Distro, DistroInfo, PackageManager


# 发行版 → 包管理器映射
_DISTRO_TO_PKG = {
    Distro.DEBIAN: PackageManager.APT,
    Distro.UBUNTU: PackageManager.APT,
    Distro.CENTOS: PackageManager.DNF,   # CentOS 8+ 用 dnf
    Distro.RHEL: PackageManager.DNF,
    Distro.ROCKY: PackageManager.DNF,
    Distro.ALMA: PackageManager.DNF,
    Distro.FEDORA: PackageManager.DNF,
    Distro.ALPINE: PackageManager.APK,
    Distro.ARCH: PackageManager.PACMAN,
}

# os-release ID 字段 → Distro 枚举
_ID_TO_DISTRO = {
    "debian": Distro.DEBIAN,
    "ubuntu": Distro.UBUNTU,
    "centos": Distro.CENTOS,
    "rhel": Distro.RHEL,
    "rocky": Distro.ROCKY,
    "rockylinux": Distro.ROCKY,
    "almalinux": Distro.ALMA,
    "alma": Distro.ALMA,
    "fedora": Distro.FEDORA,
    "alpine": Distro.ALPINE,
    "arch": Distro.ARCH,
    "archlinux": Distro.ARCH,
}


def detect_distro() -> DistroInfo:
    """检测当前发行版信息

    读取 /etc/os-release 文件，解析 ID 和 VERSION_ID。
    若无法识别，回退到通过包管理器命令探测。

    Returns:
        DistroInfo: 发行版名称、版本、包管理器
    """
    os_release = Path("/etc/os-release")

    if os_release.exists():
        info = _parse_os_release(os_release.read_text())
        distro_id = info.get("ID", "").strip('"').lower()
        version = info.get("VERSION_ID", "").strip('"')

        distro = _ID_TO_DISTRO.get(distro_id, Distro.UNKNOWN)

        if distro != Distro.UNKNOWN:
            pkg = _DISTRO_TO_PKG[distro]
            return DistroInfo(distro=distro, version=version, package_manager=pkg)

    # 回退：通过命令探测
    return _detect_by_command()


def _parse_os_release(content: str) -> dict[str, str]:
    """解析 /etc/os-release 内容为字典"""
    result: dict[str, str] = {}
    for line in content.splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _detect_by_command() -> DistroInfo:
    """通过命令探测发行版（回退方案）"""
    from .shell import which

    if which("apt-get"):
        return DistroInfo(Distro.DEBIAN, "", PackageManager.APT)
    if which("dnf"):
        return DistroInfo(Distro.CENTOS, "", PackageManager.DNF)
    if which("yum"):
        return DistroInfo(Distro.CENTOS, "", PackageManager.YUM)
    if which("apk"):
        return DistroInfo(Distro.ALPINE, "", PackageManager.APK)
    if which("pacman"):
        return DistroInfo(Distro.ARCH, "", PackageManager.PACMAN)

    return DistroInfo(Distro.UNKNOWN, "", PackageManager.UNKNOWN)


def get_install_command(pkg_manager: PackageManager, package: str) -> str:
    """获取安装命令"""
    commands = {
        PackageManager.APT: f"apt-get install -y {package}",
        PackageManager.DNF: f"dnf install -y {package}",
        PackageManager.YUM: f"yum install -y {package}",
        PackageManager.APK: f"apk add --no-cache {package}",
        PackageManager.PACMAN: f"pacman -S --noconfirm {package}",
    }
    return commands.get(pkg_manager, f"echo '不支持的包管理器: {pkg_manager}'")


def get_remove_command(pkg_manager: PackageManager, package: str) -> str:
    """获取卸载命令"""
    commands = {
        PackageManager.APT: f"apt-get remove --purge -y {package}",
        PackageManager.DNF: f"dnf remove -y {package}",
        PackageManager.YUM: f"yum remove -y {package}",
        PackageManager.APK: f"apk del {package}",
        PackageManager.PACMAN: f"pacman -R --noconfirm {package}",
    }
    return commands.get(pkg_manager, f"echo '不支持的包管理器: {pkg_manager}'")


def get_upgrade_command(pkg_manager: PackageManager, package: str) -> str:
    """获取更新命令"""
    commands = {
        PackageManager.APT: f"apt-get install --only-upgrade -y {package}",
        PackageManager.DNF: f"dnf upgrade -y {package}",
        PackageManager.YUM: f"yum update -y {package}",
        PackageManager.APK: f"apk upgrade --no-cache {package}",
        PackageManager.PACMAN: f"pacman -Syu --noconfirm {package}",
    }
    return commands.get(pkg_manager, f"echo '不支持的包管理器: {pkg_manager}'")
