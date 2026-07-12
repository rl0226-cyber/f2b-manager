"""
f2b_manager.menu
================

交互式管理菜单。

面向 VPS 新手的数字选择菜单，通过 ANSI 颜色美化输出，
覆盖 fail2ban 安装/卸载/更新、Telegram Bot 配置、运行状态查看、
IP 封禁管理、服务控制、日志查看等全部功能。

用法:
    from f2b_manager.menu import InteractiveMenu
    menu = InteractiveMenu(config_path="/etc/f2b-manager/config.yaml")
    menu.run()
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import sys
import time
from typing import Optional

import httpx

from . import __version__ as LOCAL_VERSION

# ── ANSI 颜色码 ──────────────────────────────────────
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_RED = "\033[0;31m"
C_GREEN = "\033[0;32m"
C_YELLOW = "\033[1;33m"
C_BLUE = "\033[0;34m"
C_CYAN = "\033[0;36m"
C_MAGENTA = "\033[0;35m"
C_BG_RED = "\033[41m"
C_BG_GREEN = "\033[42m"

# 终端宽度
_TERM_WIDTH = 70

# GitHub 版本检测
_REPO_API = "https://api.github.com/repos/rl0226-cyber/f2b-manager/tags"
_VERSION_CACHE = "/tmp/f2b-version-check.json"
_VERSION_CACHE_TTL = 3600  # 1 小时


def _print_separator(char: str = "─", color: str = C_DIM) -> None:
    """打印分隔线"""
    print(f"{color}{char * _TERM_WIDTH}{C_RESET}")


def _print_header(title: str) -> None:
    """打印青色标题栏"""
    print()
    _print_separator("═", C_CYAN)
    # 居中显示标题 + 版本号
    pad = max(0, (_TERM_WIDTH - len(title)) // 2)
    print(f"{C_CYAN}{' ' * pad}{C_BOLD}{title}{C_RESET}")
    _print_separator("═", C_CYAN)
    print()


def _print_success(msg: str) -> None:
    """打印成功消息"""
    print(f"  {C_GREEN}✓ {msg}{C_RESET}")


def _print_error(msg: str) -> None:
    """打印错误消息"""
    print(f"  {C_RED}✗ {msg}{C_RESET}")


def _print_warning(msg: str) -> None:
    """打印警告消息"""
    print(f"  {C_YELLOW}⚠ {msg}{C_RESET}")


def _print_info(msg: str) -> None:
    """打印信息消息"""
    print(f"  {C_CYAN}ℹ {msg}{C_RESET}")


def _clear_screen() -> None:
    """清屏"""
    print("\033[2J\033[H", end="")


def _read_input(prompt: str, default: str = "") -> str:
    """读取用户输入，空输入返回默认值"""
    if default:
        raw = input(f"  {prompt} [{default}]: ")
        return raw if raw.strip() else default
    return input(f"  {prompt}: ")


def _read_choice(prompt: str, choices: list[str], default: int = 0) -> int:
    """读取数字选择，返回选择的索引（0-based）

    输入 1-N 对应第 1 到第 N 个选项。
    输入 0 特殊映射到最后一个选项（用于"返回/退出"）。
    """
    while True:
        raw = _read_input(prompt).strip()
        if not raw:
            return default
        # 支持字母快捷键（如 U → 更新）
        raw_upper = raw.upper()
        for i, c in enumerate(choices):
            if c == raw or (c.isalpha() and c == raw_upper):
                return i
        try:
            num = int(raw)
            if num == 0:
                return len(choices) - 1  # 0 = 最后一项（返回/退出）
            idx = num - 1  # 1-based → 0-based
            if 0 <= idx < len(choices):
                return idx
            _print_error(f"请输入 0-{len(choices)} 之间的数字")
        except ValueError:
            _print_error("请输入有效数字")


def _confirm(prompt: str) -> bool:
    """二次确认，返回 True/False"""
    raw = _read_input(f"{prompt} (y/n)", "n").strip().lower()
    return raw in ("y", "yes", "是")


def _check_update() -> tuple[str, bool]:
    """检查 GitHub 是否有新版本。

    Returns:
        (latest_version, has_update): 最新版本号和是否有更新
        若检查失败返回 ("", False)
    """
    # 先读缓存
    try:
        if os.path.exists(_VERSION_CACHE):
            mtime = os.path.getmtime(_VERSION_CACHE)
            if time.time() - mtime < _VERSION_CACHE_TTL:
                with open(_VERSION_CACHE) as f:
                    data = json.load(f)
                latest = data.get("tag", "")
                has = _compare_versions(LOCAL_VERSION, latest) < 0
                return latest, has
    except Exception:
        pass

    # 查询 GitHub API (tags 列表，按时间倒序，第一个就是最新)
    try:
        resp = httpx.get(_REPO_API, timeout=10, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            # tags 端点返回数组 [{name: "v0.1.0", ...}]
            if isinstance(data, list) and len(data) > 0:
                latest = data[0].get("name", "").lstrip("v")
            elif isinstance(data, dict):
                # 兼容 releases 端点返回
                latest = data.get("tag_name", "").lstrip("v")
            else:
                return "", False
            # 写入缓存
            with open(_VERSION_CACHE, "w") as f:
                json.dump({"tag": latest, "ts": time.time()}, f)
            has = _compare_versions(LOCAL_VERSION, latest) < 0
            return latest, has
    except Exception:
        pass

    return "", False


def _compare_versions(a: str, b: str) -> int:
    """比较两个版本号。

    Returns:
        1  (a > b), -1 (a < b), 0 (相等)
    """
    try:
        from packaging.version import Version
        return (Version(a) > Version(b)) - (Version(a) < Version(b))
    except ImportError:
        # 简易比较：按数字段
        def _parse(v):
            return [int(x) for x in re.findall(r"\d+", v)]
        pa, pb = _parse(a), _parse(b)
        return (pa > pb) - (pa < pb)


def _check_pkg_update(package: str) -> tuple[str, bool]:
    """通过包管理器检查软件包是否有可用更新。

    Returns:
        (available_version, has_update)
    """
    try:
        # APT (Debian/Ubuntu)
        r = subprocess.run(
            ["apt-cache", "policy", package],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            installed = ""
            candidate = ""
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("Installed:"):
                    installed = line.split(":", 1)[1].strip()
                    if installed == "(none)":
                        installed = ""
                elif line.startswith("Candidate:"):
                    candidate = line.split(":", 1)[1].strip()
            if installed and candidate and installed != candidate:
                # 去掉 epoch 前缀（如 1:1.1.0-1 → 1.1.0-1）
                installed = installed.split(":", 1)[-1] if ":" in installed else installed
                candidate = candidate.split(":", 1)[-1] if ":" in candidate else candidate
                return candidate, _compare_versions(installed, candidate) < 0
            return candidate, False
    except Exception:
        pass

    try:
        # DNF (CentOS/RHEL/Rocky/Fedora)
        r = subprocess.run(
            ["dnf", "list", "available", package],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].startswith(package):
                    return parts[1], True
    except Exception:
        pass

    return "", False


class InteractiveMenu:
    """交互式管理菜单。

    面向 VPS 新手设计，所有操作通过数字选择完成。
    使用 ANSI 颜色码美化输出。
    """

    def __init__(self, config_path: str = "/etc/f2b-manager/config.yaml"):
        self._config_path = config_path
        self._config = None
        self._f2b_manager = None
        self._f2b_installer = None
        self._latest_version = ""
        self._has_update = False
        # fail2ban 状态（安装检查 + 版本）
        self._f2b_installed: Optional[bool] = None
        self._f2b_version: str = ""
        self._f2b_latest: str = ""
        self._f2b_has_update: bool = False

    # ── 主循环 ────────────────────────────────────

    def run(self) -> None:
        """启动交互式菜单主循环"""
        # 加载配置
        from .config import load_config
        self._config = load_config(self._config_path)

        # 初始化 fail2ban 模块
        self._init_modules()

        # 检查 f2b-manager 更新
        self._latest_version, self._has_update = _check_update()

        # 检查 fail2ban 状态和版本
        self._check_fail2ban_status()

        while True:
            _clear_screen()
            self._show_main_menu()
            # 特殊处理 "0" → 退出（菜单显示 [0] 退出）
            raw = _read_input("请选择操作").strip()
            if raw == "0":
                print()
                print(f"{C_GREEN}  再见！使用 'f2b' 或 'f2b-manager menu' 可再次打开菜单。{C_RESET}")
                print()
                break

            raw_upper = raw.upper()
            # 字母快捷键
            if raw_upper == "U":
                self._menu_update_manager()
                continue
            if raw_upper == "D":
                self._menu_uninstall_manager()
                continue

            try:
                idx = int(raw) - 1  # 1-based → 0-based
            except ValueError:
                _print_error("请输入有效数字")
                _read_input("按 Enter 继续")
                continue
            if idx < 0 or idx > 8:
                _print_error("请输入 0-9 之间的数字，或 U 更新 / D 卸载 f2b-manager")
                _read_input("按 Enter 继续")
                continue

            choice = idx
            print()

            if choice == 0:
                self._menu_install()
            elif choice == 1:
                self._menu_uninstall()
            elif choice == 2:
                self._menu_update()
            elif choice == 3:
                self._menu_config_telegram()
            elif choice == 4:
                self._menu_status()
            elif choice == 5:
                self._menu_banned_ips()
            elif choice == 6:
                self._menu_ban_manage()
            elif choice == 7:
                self._menu_service_control()
            elif choice == 8:
                self._menu_view_logs()

    def _init_modules(self) -> None:
        """延迟初始化 fail2ban 相关模块"""
        # Fail2banManager（无需 config 参数）
        try:
            from .fail2ban.manager import Fail2banManager
            self._f2b_manager = Fail2banManager()
        except ImportError:
            self._f2b_manager = None

        # Fail2banInstaller（需要 Fail2banConfig）
        try:
            from .fail2ban.installer import Fail2banInstaller
            self._f2b_installer = Fail2banInstaller(self._config.fail2ban)
        except ImportError:
            self._f2b_installer = None

    def _check_fail2ban_status(self) -> None:
        """检查 fail2ban 安装状态、版本和可用更新"""
        # 1. 是否安装
        try:
            from shutil import which
            if which("fail2ban-client"):
                self._f2b_installed = True
                try:
                    result = subprocess.run(
                        ["fail2ban-client", "version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if result.returncode == 0:
                        self._f2b_version = result.stdout.strip().splitlines()[0].strip()
                except Exception:
                    self._f2b_version = "?"
            else:
                self._f2b_installed = False
        except Exception:
            self._f2b_installed = False

        if not self._f2b_installed:
            return

        # 2. 检查是否有可用更新（通过包管理器）
        self._f2b_latest, self._f2b_has_update = _check_pkg_update("fail2ban")
        """延迟初始化 fail2ban 相关模块"""
        try:
            from .fail2ban.manager import Fail2banManager
            self._f2b_manager = Fail2banManager()
        except ImportError:
            self._f2b_manager = None

        try:
            from .fail2ban.installer import Fail2banInstaller
            self._f2b_installer = Fail2banInstaller(self._config.fail2ban)
        except ImportError:
            self._f2b_installer = None

    def _show_main_menu(self) -> None:
        """显示主菜单（含版本信息和更新提示）"""
        _print_header("f2b-manager 管理菜单")

        # ── f2b-manager 版本行 ──
        ver_line = f"  f2b-manager: {C_GREEN}v{LOCAL_VERSION}{C_RESET}"
        if self._has_update:
            ver_line += (
                f"  {C_YELLOW}{C_BOLD}🆕 新版本 v{self._latest_version}"
                f" → 输入 U 更新{C_RESET}"
            )
        elif self._latest_version:
            ver_line += f"  {C_DIM}(已是最新){C_RESET}"
        print(ver_line)

        # ── fail2ban 状态行 ──
        if self._f2b_installed is None:
            pass  # 未检测
        elif self._f2b_installed:
            f2b_line = f"  fail2ban:    {C_GREEN}已安装{C_RESET}"
            if self._f2b_version:
                f2b_line += f"  v{self._f2b_version}"
            if self._f2b_has_update and self._f2b_latest:
                f2b_line += (
                    f"  {C_YELLOW}{C_BOLD}🆕 可升级至 {self._f2b_latest}"
                    f" → 选 [3] 更新{C_RESET}"
                )
            else:
                f2b_line += f"  {C_DIM}(已是最新){C_RESET}"
            print(f2b_line)
        else:
            print(f"  fail2ban:    {C_RED}未安装{C_RESET}  → 选 [1] 安装")
        print()

        menu_items = [
            ("1", "安装 Fail2ban", "自动检测发行版并安装 fail2ban"),
            ("2", "卸载 Fail2ban", "停止服务、备份配置并卸载"),
            ("3", "更新 Fail2ban", "升级到最新版本"),
            ("4", "配置 Telegram Bot 通知", "引导式配置 Bot Token、Chat ID"),
            ("5", "查看运行状态", "查看 fail2ban 服务状态与 jail 信息"),
            ("6", "查看封禁 IP 列表", "列出所有当前被封禁的 IP"),
            ("7", "手动封禁 / 解封 IP", "手动添加或移除 IP 封禁"),
            ("8", "启动 / 停止 / 重启服务", "管理 f2b-manager 和 fail2ban 服务"),
            ("9", "查看日志", "查看最近的运行日志"),
            ("U", "更新 f2b-manager", "更新管理程序到最新版本"),
            ("D", "卸载 f2b-manager", "移除管理程序和所有组件"),
            ("0", "退出", "退出管理菜单"),
        ]
        for num, title, desc in menu_items:
            color = C_YELLOW if num == "U" and self._has_update else C_GREEN
            print(f"  {C_BOLD}{color}[{num}]{C_RESET} {C_BOLD}{title}{C_RESET}")
            print(f"   {C_DIM}{desc}{C_RESET}")
        print()

    # ── 1. 安装 Fail2ban ─────────────────────────

    def _menu_install(self) -> None:
        """安装 Fail2ban"""
        _clear_screen()
        _print_header("安装 Fail2ban")

        if self._f2b_installer is None:
            _print_error("Fail2ban 安装模块未就绪，请确认程序完整安装")
            _read_input("按 Enter 返回")
            return

        _print_info("正在检测系统并安装 fail2ban，请稍候...")
        print()

        try:
            result = self._f2b_installer.install()
            if result.success:
                _print_success(result.message)
                if result.version:
                    print(f"  {C_GREEN}  版本: {result.version}{C_RESET}")
                if result.details:
                    print(f"  {C_DIM}  详情:{C_RESET}")
                    for d in result.details:
                        print(f"    {C_DIM}• {d}{C_RESET}")
            else:
                _print_error(result.message)
                if result.details:
                    for d in result.details:
                        print(f"    {C_DIM}• {d}{C_RESET}")
        except Exception as e:
            _print_error(f"安装过程异常: {e}")

        print()
        _read_input("按 Enter 返回主菜单")

    # ── 2. 卸载 Fail2ban ─────────────────────────

    def _menu_uninstall(self) -> None:
        """卸载 Fail2ban"""
        _clear_screen()
        _print_header("卸载 Fail2ban")

        if self._f2b_installer is None:
            _print_error("Fail2ban 安装模块未就绪")
            _read_input("按 Enter 返回")
            return

        if not _confirm("确定要卸载 Fail2ban 吗？此操作不可逆"):
            print(f"  {C_DIM}已取消{C_RESET}")
            _read_input("按 Enter 返回")
            return

        print()
        _print_info("正在卸载 fail2ban，请稍候...")
        print()

        try:
            result = self._f2b_installer.uninstall(keep_config=True)
            if result.success:
                _print_success(result.message)
                if result.details:
                    for d in result.details:
                        print(f"    {C_DIM}• {d}{C_RESET}")
            else:
                _print_error(result.message)
        except Exception as e:
            _print_error(f"卸载过程异常: {e}")

        print()
        _read_input("按 Enter 返回主菜单")

    # ── 3. 更新 Fail2ban ─────────────────────────

    def _menu_update(self) -> None:
        """更新 Fail2ban"""
        _clear_screen()
        _print_header("更新 Fail2ban")

        if self._f2b_installer is None:
            _print_error("Fail2ban 安装模块未就绪")
            _read_input("按 Enter 返回")
            return

        _print_info("正在检查并更新 fail2ban...")
        print()

        try:
            result = self._f2b_installer.update()
            if result.success:
                _print_success(result.message)
                if result.version:
                    print(f"  {C_GREEN}  版本: {result.version}{C_RESET}")
                if result.details:
                    for d in result.details:
                        print(f"    {C_DIM}• {d}{C_RESET}")
            else:
                _print_error(result.message)
                if result.details:
                    for d in result.details:
                        print(f"    {C_DIM}• {d}{C_RESET}")
        except Exception as e:
            _print_error(f"更新过程异常: {e}")

        print()
        _read_input("按 Enter 返回主菜单")

    # ── U. 更新 f2b-manager ──────────────────────

    def _menu_update_manager(self) -> None:
        """更新 f2b-manager 自身"""
        _clear_screen()
        _print_header("更新 f2b-manager")

        print(f"  当前版本: {C_GREEN}{LOCAL_VERSION}{C_RESET}")
        if self._latest_version:
            print(f"  最新版本: {C_YELLOW}{self._latest_version}{C_RESET}")
        print()

        if not _confirm("确定要更新 f2b-manager 到最新版本吗？"):
            print(f"  {C_DIM}已取消{C_RESET}")
            _read_input("按 Enter 返回")
            return

        # 确定源代码路径
        repo_dir = "/tmp/f2b-manager"
        if not os.path.isdir(os.path.join(repo_dir, ".git")):
            _print_info("正在克隆仓库...")
            r = subprocess.run(
                ["git", "clone", "https://github.com/rl0226-cyber/f2b-manager.git", repo_dir],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                _print_error(f"克隆仓库失败: {r.stderr}")
                _read_input("按 Enter 返回")
                return

        # git pull
        _print_info("正在拉取最新代码...")
        r = subprocess.run(
            ["git", "-C", repo_dir, "pull", "origin", "main"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            _print_error(f"拉取代码失败: {r.stderr}")
            _read_input("按 Enter 返回")
            return

        # 检查是否有更新
        if "Already up to date" in r.stdout or "Already up-to-date" in r.stdout:
            _print_success("已是最新版本，无需更新")
            _read_input("按 Enter 返回")
            return

        _print_success("代码已更新")

        # 复制文件
        _print_info("正在部署更新...")
        src = os.path.join(repo_dir, "f2b_manager")
        dst = "/opt/f2b-manager/f2b_manager"
        r = subprocess.run(
            ["cp", "-r", f"{src}/", dst],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            _print_error(f"部署失败: {r.stderr}")
            _read_input("按 Enter 返回")
            return

        _print_success("文件已部署")

        # 重启服务
        _print_info("正在重启服务...")
        r = subprocess.run(
            ["systemctl", "restart", "f2b-manager"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            _print_success("服务已重启，更新完成！")
        else:
            _print_warning(f"服务重启可能失败: {r.stderr}")
            _print_info("请手动执行: systemctl restart f2b-manager")

        # 清除版本缓存
        if os.path.exists(_VERSION_CACHE):
            os.remove(_VERSION_CACHE)

        print()
        print(f"  {C_GREEN}更新完成！下次打开菜单将显示新版本号。{C_RESET}")
        print()
        _read_input("按 Enter 返回主菜单")

    # ── D. 卸载 f2b-manager ──────────────────────

    def _menu_uninstall_manager(self) -> None:
        """卸载 f2b-manager 自身"""
        _clear_screen()
        _print_header("卸载 f2b-manager")

        print(f"  {C_YELLOW}{C_BOLD}⚠️  警告：此操作将移除 f2b-manager 及其所有组件{C_RESET}")
        print()
        print(f"  将删除以下内容：")
        print(f"    • /opt/f2b-manager/  (程序文件)")
        print(f"    • /etc/f2b-manager/  (配置文件)")
        print(f"    • /usr/local/bin/f2b-manager (CLI)")
        print(f"    • /usr/local/bin/f2b (快捷指令)")
        print(f"    • /usr/local/bin/f2b-notify.sh (通知脚本)")
        print(f"    • systemd 服务")
        print(f"    • /var/lib/f2b-manager/ (数据库)")
        print()
        print(f"  {C_GREEN}以下内容不受影响：{C_RESET}")
        print(f"    • fail2ban 及其配置")
        print(f"    • Telegram Bot（需在 BotFather 手动删除）")
        print()

        if not _confirm("确定要卸载 f2b-manager 吗？此操作不可逆！"):
            print(f"  {C_DIM}已取消{C_RESET}")
            _read_input("按 Enter 返回主菜单")
            return

        # 二次确认
        if not _confirm("再次确认：你真的要卸载 f2b-manager 吗？"):
            print(f"  {C_DIM}已取消{C_RESET}")
            _read_input("按 Enter 返回主菜单")
            return

        print()
        _print_info("正在卸载 f2b-manager...")

        errors = []

        # 1. 停止并禁用服务
        for svc in ["f2b-manager"]:
            r = subprocess.run(["systemctl", "stop", svc], capture_output=True, text=True)
            r2 = subprocess.run(["systemctl", "disable", svc], capture_output=True, text=True)
            if r.returncode == 0 or "not loaded" in r.stderr.lower():
                _print_success(f"服务 {svc} 已停止并禁用")
            else:
                errors.append(f"停止 {svc}: {r.stderr.strip()}")

        # 2. 删除 systemd 文件
        svc_file = "/etc/systemd/system/f2b-manager.service"
        if os.path.exists(svc_file):
            os.remove(svc_file)
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
            _print_success("systemd 服务文件已删除")

        # 3. 删除可执行文件和快捷指令
        for f in ["/usr/local/bin/f2b-manager", "/usr/local/bin/f2b-notify.sh"]:
            if os.path.lexists(f):
                os.remove(f)
                _print_success(f"已删除: {f}")
        # f2b 是 symlink
        if os.path.lexists("/usr/local/bin/f2b"):
            os.remove("/usr/local/bin/f2b")
            _print_success("已删除: /usr/local/bin/f2b")

        # 4. 删除程序目录
        import shutil
        for d in ["/opt/f2b-manager", "/var/lib/f2b-manager"]:
            if os.path.isdir(d):
                shutil.rmtree(d)
                _print_success(f"已删除: {d}")

        # 5. 询问是否保留配置
        if os.path.isdir("/etc/f2b-manager"):
            if _confirm("是否保留配置文件 /etc/f2b-manager/？（方便以后重新安装）"):
                print(f"  {C_DIM}配置文件已保留在 /etc/f2b-manager/{C_RESET}")
            else:
                shutil.rmtree("/etc/f2b-manager")
                _print_success("配置文件已删除")

        # 6. 清理版本缓存
        if os.path.exists(_VERSION_CACHE):
            os.remove(_VERSION_CACHE)

        print()
        if errors:
            _print_warning(f"卸载过程中有 {len(errors)} 个警告")
            for e in errors:
                print(f"    {C_DIM}• {e}{C_RESET}")
        else:
            _print_success("f2b-manager 已完全卸载！")

        print()
        print(f"  {C_GREEN}感谢使用 f2b-manager！{C_RESET}")
        print()

    # ── 4. 配置 Telegram Bot ─────────────────────

    def _menu_config_telegram(self) -> None:
        """引导式配置 Telegram Bot"""
        _clear_screen()
        _print_header("配置 Telegram Bot 通知")
        print("  本向导将引导你完成 Telegram Bot 配置，无需手动编辑文件。")
        print()
        print(f"  {C_BOLD}【第 1 步】创建 Bot{C_RESET}")
        print("    1. 打开 Telegram，搜索 @BotFather")
        print("    2. 发送 /newbot，按提示输入 Bot 名称和用户名")
        print("    3. 复制返回的 Bot Token（格式如 123456789:ABCdef...）")
        print()

        while True:
            token = _read_input("请输入 Bot Token（格式: 数字:字母数字串）").strip()
            if not token:
                _print_error("Token 不能为空")
                continue
            # 校验格式
            if re.match(r"^\d+:[A-Za-z0-9_-]+$", token):
                break
            _print_error("Token 格式不正确，应为 数字:字母数字串")
        _print_success("Token 格式校验通过")
        print()

        print(f"  {C_BOLD}【第 2 步】获取你的 Chat ID{C_RESET}")
        print("    1. 在 Telegram 搜索 @userinfobot")
        print("    2. 给它发任意消息")
        print("    3. 它会回复你的 User ID（纯数字）")
        print()

        while True:
            chat_id_raw = _read_input("请输入你的 Telegram Chat ID（纯数字）").strip()
            if not chat_id_raw:
                _print_error("Chat ID 不能为空")
                continue
            if chat_id_raw.isdigit():
                break
            _print_error("Chat ID 应为纯数字")
        chat_id = int(chat_id_raw)
        print()

        # 可选：操作员
        extra = _read_input("输入额外的操作员 Chat ID（可选，直接按 Enter 跳过）").strip()
        extra_ids = []
        if extra:
            for eid in extra.split(","):
                eid = eid.strip()
                if eid.isdigit():
                    extra_ids.append(int(eid))
        print()

        print(f"  {C_BOLD}【第 3 步】验证连接{C_RESET}")
        _print_info("正在发送测试消息到 Telegram...")

        send_ok = False
        try:
            resp = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": "✅ f2b-manager 配置测试成功！\n\n你的 Bot 已就绪，封禁预警将自动推送。",
                },
                timeout=10,
            )
            data = resp.json() if resp.status_code == 200 else {}
            if data.get("ok"):
                send_ok = True
                _print_success("测试消息已发送，请打开 Telegram 查看")
            else:
                _print_error(f"测试消息发送失败: {data.get('description', resp.text[:200])}")
        except Exception as e:
            _print_error(f"测试消息发送失败: {e}")

        if not send_ok:
            print()
            print(f"  {C_YELLOW}可能原因:{C_RESET}")
            print("    - Token 不正确或已过期")
            print("    - Chat ID 不正确")
            print("    - 需要先在 Telegram 给 Bot 发一条任意消息")
            print("    - VPS 网络不通，无法访问 Telegram API")

        print()
        if not send_ok and not _confirm("测试消息发送失败，是否仍然保存配置？"):
            print(f"  {C_DIM}已取消{C_RESET}")
            _read_input("按 Enter 返回")
            return

        # 保存配置
        print()
        _print_info("正在保存配置...")

        from .config import save_config
        self._config.telegram.bot_token = token
        self._config.telegram.admin_chat_ids = [chat_id] + extra_ids
        self._config.telegram.notify_chat_id = chat_id
        if extra_ids:
            self._config.telegram.operator_chat_ids = extra_ids

        save_config(self._config, self._config_path)
        _print_success(f"配置已保存到: {self._config_path}")

        print()
        _print_info("配置完成！需要重启服务才能生效")
        if _confirm("是否立即重启 f2b-manager 服务？"):
            r = subprocess.run(["systemctl", "restart", "f2b-manager"], capture_output=True)
            if r.returncode == 0:
                _print_success("服务已重启")
            else:
                _print_warning("服务重启失败，请手动执行: systemctl restart f2b-manager")
        else:
            print(f"  {C_DIM}可稍后执行: systemctl restart f2b-manager{C_RESET}")

        print()
        _read_input("按 Enter 返回主菜单")

    # ── 5. 查看运行状态 ──────────────────────────

    def _menu_status(self) -> None:
        """查看 Fail2ban 运行状态"""
        _clear_screen()
        _print_header("Fail2ban 运行状态")

        if self._f2b_manager is None:
            _print_error("Fail2ban 管理模块未就绪")
            _read_input("按 Enter 返回")
            return

        try:
            from .utils.shell import run_command
            status = self._f2b_manager.get_status()
            print(f"  版本: {C_GREEN}{status.version}{C_RESET}")
            state_color = C_GREEN if status.state.value == "running" else C_RED
            print(f"  状态: {state_color}{status.state.value}{C_RESET}")
            print(f"  Jail 数: {status.jail_count}")
            print(f"  总封禁: {status.total_bans}")
            print(f"  运行时长: {status.uptime}")
            print()

            # 各 jail 详情
            jails = self._f2b_manager.get_jails()
            if jails:
                print(f"  {C_BOLD}Jail 列表:{C_RESET}")
                for j in jails:
                    icon = "✅" if j.enabled else "❌"
                    print(f"    {icon} {j.name}: 封禁 {j.current_ban} | 失败 {j.total_failed} | 累计 {j.total_banned}")
        except Exception as e:
            _print_error(f"获取状态失败: {e}")
            _print_info("提示: 请确认 fail2ban 已安装并运行")
            _print_info("可尝试: systemctl status fail2ban")

        print()
        _read_input("按 Enter 返回主菜单")

    # ── 6. 查看封禁 IP 列表 ──────────────────────

    def _menu_banned_ips(self) -> None:
        """查看封禁 IP 列表"""
        _clear_screen()
        _print_header("封禁 IP 列表")

        if self._f2b_manager is None:
            _print_error("Fail2ban 管理模块未就绪")
            _read_input("按 Enter 返回")
            return

        try:
            ips = self._f2b_manager.get_banned_ips()
            if not ips:
                _print_success("当前无封禁 IP")
            else:
                print(f"  {C_BOLD}共 {len(ips)} 个 IP 被封禁:{C_RESET}")
                print()
                for i, ip in enumerate(ips, 1):
                    print(f"  {C_BOLD}{i}.{C_RESET} {C_RED}{ip}{C_RESET}")
        except Exception as e:
            _print_error(f"获取封禁列表失败: {e}")

        print()
        _read_input("按 Enter 返回主菜单")

    # ── 7. 手动封禁 / 解封 IP ────────────────────

    def _menu_ban_manage(self) -> None:
        """手动封禁/解封 子菜单"""
        _clear_screen()
        while True:
            _print_header("手动封禁 / 解封 IP")
            menu_items = [
                ("1", "封禁 IP", "手动封禁指定 IP 地址"),
                ("2", "解封 IP", "手动解封指定 IP 地址"),
                ("0", "返回", "返回主菜单"),
            ]
            for num, title, desc in menu_items:
                print(f"  {C_BOLD}{C_GREEN}[{num}]{C_RESET} {C_BOLD}{title}{C_RESET}")
                print(f"   {C_DIM}{desc}{C_RESET}")
            print()

            choice = _read_choice("请选择操作", [str(i) for i in range(len(menu_items))])
            print()

            if choice == 0:
                self._menu_ban_ip()
            elif choice == 1:
                self._menu_unban_ip()
            elif choice == 2:
                break

    def _menu_ban_ip(self) -> None:
        """封禁 IP 子流程"""
        _clear_screen()
        _print_header("手动封禁 IP")

        if self._f2b_manager is None:
            _print_error("Fail2ban 管理模块未就绪")
            _read_input("按 Enter 返回")
            return

        while True:
            ip = _read_input("请输入要封禁的 IP 地址（如 192.168.1.100）").strip()
            if not ip:
                continue
            try:
                ipaddress.ip_address(ip)
                break
            except ValueError:
                _print_error("IP 地址格式不正确，请输入有效 IPv4 地址")

        jail = _read_input("请输入 jail 名称（默认: sshd）", "sshd").strip()
        print()

        try:
            success = self._f2b_manager.ban_ip(ip, jail)
            if success:
                _print_success(f"已封禁 {ip}（jail: {jail}）")
            else:
                _print_error(f"封禁 {ip} 失败")
        except Exception as e:
            _print_error(f"封禁失败: {e}")

        print()
        _read_input("按 Enter 继续")

    def _menu_unban_ip(self) -> None:
        """解封 IP 子流程"""
        _clear_screen()
        _print_header("手动解封 IP")

        if self._f2b_manager is None:
            _print_error("Fail2ban 管理模块未就绪")
            _read_input("按 Enter 返回")
            return

        while True:
            ip = _read_input("请输入要解封的 IP 地址").strip()
            if not ip:
                continue
            try:
                ipaddress.ip_address(ip)
                break
            except ValueError:
                _print_error("IP 地址格式不正确，请输入有效 IPv4 地址")

        # 检查是否被封禁
        found_jail = None
        try:
            for j in self._f2b_manager.get_jails():
                js = self._f2b_manager.get_jail_status(j.name)
                if ip in js.banned_ips:
                    found_jail = j.name
                    break
        except Exception:
            pass

        if found_jail is None:
            _print_warning(f"{ip} 不在任何 jail 的封禁列表中，无需解封")
            print()
            _read_input("按 Enter 继续")
            return

        print()
        try:
            success = self._f2b_manager.unban_ip(ip)
            if success:
                _print_success(f"已解封 {ip}（原 jail: {found_jail}）")
            else:
                _print_error(f"解封 {ip} 失败")
        except Exception as e:
            _print_error(f"解封失败: {e}")

        print()
        _read_input("按 Enter 继续")

    # ── 8. 服务控制 ──────────────────────────────

    def _menu_service_control(self) -> None:
        """启动/停止/重启 子菜单"""
        _clear_screen()
        while True:
            _print_header("服务控制")
            menu_items = [
                ("1", "启动 f2b-manager", "启动守护进程"),
                ("2", "停止 f2b-manager", "停止守护进程"),
                ("3", "重启 f2b-manager", "重启守护进程"),
                ("4", "启动 fail2ban", "启动 fail2ban 入侵防御服务"),
                ("5", "停止 fail2ban", "停止 fail2ban 入侵防御服务"),
                ("6", "重启 fail2ban", "重启 fail2ban 入侵防御服务"),
                ("7", "查看服务状态", "查看两个服务的 systemctl 状态"),
                ("0", "返回", "返回主菜单"),
            ]
            for num, title, desc in menu_items:
                print(f"  {C_BOLD}{C_GREEN}[{num}]{C_RESET} {C_BOLD}{title}{C_RESET}")
                print(f"   {C_DIM}{desc}{C_RESET}")
            print()

            choice = _read_choice("请选择操作", [str(i) for i in range(len(menu_items))])
            print()

            if choice == 0:
                self._systemctl("start", "f2b-manager")
            elif choice == 1:
                if _confirm("确定要停止 f2b-manager 服务吗？"):
                    self._systemctl("stop", "f2b-manager")
            elif choice == 2:
                self._systemctl("restart", "f2b-manager")
            elif choice == 3:
                self._systemctl("start", "fail2ban")
            elif choice == 4:
                if _confirm("确定要停止 fail2ban 服务吗？停止后将不再防御入侵攻击"):
                    self._systemctl("stop", "fail2ban")
            elif choice == 5:
                self._systemctl("restart", "fail2ban")
            elif choice == 6:
                self._systemctl_status()
            elif choice == 7:
                break

    def _systemctl(self, action: str, service: str) -> None:
        """执行 systemctl 命令"""
        r = subprocess.run(
            ["systemctl", action, service],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            _print_success(f"systemctl {action} {service} 成功")
        else:
            _print_error(f"systemctl {action} {service} 失败: {r.stderr.strip()}")

    def _systemctl_status(self) -> None:
        """查看服务状态"""
        print(f"  {C_BOLD}f2b-manager:{C_RESET}")
        r = subprocess.run(
            ["systemctl", "is-active", "f2b-manager"],
            capture_output=True, text=True,
        )
        status = "active" if "active" in r.stdout else r.stdout.strip()
        color = C_GREEN if status == "active" else C_RED
        print(f"    状态: {color}{status}{C_RESET}")

        print(f"  {C_BOLD}fail2ban:{C_RESET}")
        r = subprocess.run(
            ["systemctl", "is-active", "fail2ban"],
            capture_output=True, text=True,
        )
        status = "active" if "active" in r.stdout else r.stdout.strip()
        color = C_GREEN if status == "active" else C_RED
        print(f"    状态: {color}{status}{C_RESET}")

    # ── 9. 查看日志 ──────────────────────────────

    def _menu_view_logs(self) -> None:
        """查看日志"""
        _clear_screen()
        _print_header("运行日志（最近 50 行）")

        r = subprocess.run(
            ["journalctl", "-u", "f2b-manager", "--no-pager", "-n", "50"],
            capture_output=True, text=True,
        )
        if r.stdout:
            print(r.stdout)
        else:
            _print_info("无日志或日志为空")

        print()
        _read_input("按 Enter 返回主菜单")
