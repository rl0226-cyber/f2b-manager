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
import os
import re
import sys
import time
from typing import Optional

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


def _print_separator(char: str = "─", color: str = C_DIM) -> None:
    """打印分隔线"""
    print(f"{color}{char * _TERM_WIDTH}{C_RESET}")


def _print_header(title: str) -> None:
    """打印青色标题栏"""
    print()
    _print_separator("═", C_CYAN)
    print(f"  {C_CYAN}{C_BOLD}{title}{C_RESET}")
    _print_separator("═", C_CYAN)
    print()


def _print_success(msg: str) -> None:
    """打印绿色成功消息"""
    print(f"  {C_GREEN}✓ {msg}{C_RESET}")


def _print_error(msg: str) -> None:
    """打印红色错误消息"""
    print(f"  {C_RED}✗ {msg}{C_RESET}")


def _print_warning(msg: str) -> None:
    """打印黄色警告消息"""
    print(f"  {C_YELLOW}⚠ {msg}{C_RESET}")


def _print_info(msg: str) -> None:
    """打印蓝色提示消息"""
    print(f"  {C_BLUE}ℹ {msg}{C_RESET}")


def _print_progress(msg: str) -> None:
    """打印进行中消息"""
    print(f"  {C_CYAN}⏳ {msg}...{C_RESET}", end="", flush=True)


def _print_done() -> None:
    """完成标记"""
    print(f"\r  {C_GREEN}✓ 完成{C_RESET}" + " " * 20)


def _read_input(prompt: str, default: str = "") -> str:
    """读取用户输入（带青色提示前缀）"""
    if default:
        display_prompt = f"  {prompt} [{default}]: "
    else:
        display_prompt = f"  {prompt}: "
    try:
        value = input(display_prompt).strip()
        return value if value else default
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _read_choice(prompt: str, choices: list[str], default: int = 0) -> int:
    """读取数字选择，返回选择的索引（0-based）

    输入 1-N 对应第 1 到第 N 个选项。
    输入 0 特殊映射到最后一个选项（用于"返回/退出"）。
    """
    while True:
        raw = _read_input(prompt).strip()
        if not raw:
            return default
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

    # ── 主循环 ────────────────────────────────────

    def run(self) -> None:
        """启动交互式菜单主循环"""
        # 加载配置
        from .config import load_config
        self._config = load_config(self._config_path)

        # 初始化 fail2ban 模块
        self._init_modules()

        while True:
            self._show_main_menu()
            # 特殊处理 "0" → 退出（菜单显示 [0] 退出，但 _read_choice 用 1-based）
            raw = _read_input("请选择操作").strip()
            if raw == "0":
                print()
                print(f"{C_GREEN}  再见！使用 'f2b' 或 'f2b-manager menu' 可再次打开菜单。{C_RESET}")
                print()
                break
            try:
                idx = int(raw) - 1  # 1-based → 0-based
            except ValueError:
                _print_error("请输入有效数字")
                continue
            if idx < 0 or idx > 8:
                _print_error("请输入 0-9 之间的数字")
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

    def _show_main_menu(self) -> None:
        """显示主菜单"""
        _print_header("f2b-manager 管理菜单")
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
            ("0", "退出", "退出管理菜单"),
        ]
        for num, title, desc in menu_items:
            print(f"  {C_BOLD}{C_GREEN}[{num}]{C_RESET} {C_BOLD}{title}{C_RESET}")
            print(f"   {C_DIM}{desc}{C_RESET}")
        print()

    # ── 1. 安装 Fail2ban ─────────────────────────

    def _menu_install(self) -> None:
        """安装 Fail2ban"""
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
                        print(f"    {C_RED}• {d}{C_RESET}")
        except Exception as e:
            _print_error(f"安装过程发生错误: {e}")

        print()
        _read_input("按 Enter 返回主菜单")

    # ── 2. 卸载 Fail2ban ─────────────────────────

    def _menu_uninstall(self) -> None:
        """卸载 Fail2ban（二次确认）"""
        _print_header("卸载 Fail2ban")

        if self._f2b_installer is None:
            _print_error("Fail2ban 安装模块未就绪，请确认程序完整安装")
            _read_input("按 Enter 返回")
            return

        print(f"  {C_RED}{C_BOLD}⚠ 此操作将停止 fail2ban 服务并卸载软件包{C_RESET}")
        print(f"  {C_DIM}  配置文件会备份到 /etc/fail2ban.backup.* 目录{C_RESET}")
        print()

        if not _confirm("确定要卸载 Fail2ban？"):
            _print_info("已取消卸载")
            _read_input("按 Enter 返回")
            return

        print()
        _print_progress("正在卸载 fail2ban")
        try:
            result = self._f2b_installer.uninstall(keep_config=True)
            _print_done()
            if result.success:
                _print_success(result.message)
                if result.details:
                    for d in result.details:
                        print(f"    {C_DIM}• {d}{C_RESET}")
            else:
                _print_error(result.message)
        except Exception as e:
            _print_error(f"卸载过程发生错误: {e}")

        print()
        _read_input("按 Enter 返回主菜单")

    # ── 3. 更新 Fail2ban ─────────────────────────

    def _menu_update(self) -> None:
        """更新 Fail2ban"""
        _print_header("更新 Fail2ban")

        if self._f2b_installer is None:
            _print_error("Fail2ban 安装模块未就绪，请确认程序完整安装")
            _read_input("按 Enter 返回")
            return

        _print_progress("正在更新 fail2ban")
        try:
            result = self._f2b_installer.update()
            _print_done()
            if result.success:
                _print_success(result.message)
                if result.details:
                    for d in result.details:
                        print(f"    {C_DIM}• {d}{C_RESET}")
            else:
                _print_error(result.message)
                if result.details:
                    for d in result.details:
                        print(f"    {C_RED}• {d}{C_RESET}")
        except Exception as e:
            _print_error(f"更新过程发生错误: {e}")

        print()
        _read_input("按 Enter 返回主菜单")

    # ── 4. 配置 Telegram Bot（引导式）────────────

    def _menu_config_telegram(self) -> None:
        """引导式配置 Telegram Bot 通知"""
        _print_header("配置 Telegram Bot 通知")

        print(f"  {C_CYAN}此向导将帮助你创建并配置 Telegram Bot 通知功能。{C_RESET}")
        print()
        print(f"  {C_BOLD}准备工作：{C_RESET}")
        print(f"  {C_DIM}  1. 在 Telegram 中搜索 @BotFather{C_RESET}")
        print(f"  {C_DIM}  2. 发送 /newbot 创建机器人{C_RESET}")
        print(f"  {C_DIM}  3. 按提示输入机器人名称和用户名{C_RESET}")
        print(f"  {C_DIM}  4. 复制收到的 Bot Token（格式: 数字:字母数字串）{C_RESET}")
        print(f"  {C_DIM}  5. 给新 Bot 发送任意消息（如 /start）{C_RESET}")
        print(f"  {C_DIM}  6. 访问 https://api.telegram.org/bot<你的Token>/getUpdates 获取 Chat ID{C_RESET}")
        print()

        # ── 输入 Bot Token ──
        while True:
            print(f"  {C_BOLD}步骤 1/3: Bot Token{C_RESET}")
            token = _read_input("请输入 Bot Token（格式: 数字:字母数字串）")
            if not token:
                _print_info("已取消配置")
                _read_input("按 Enter 返回")
                return
            if self._validate_token(token):
                _print_success("Token 格式校验通过")
                break
            _print_error("Token 格式不正确，应为 数字:字母数字串格式")
            print()

        # ── 输入 Chat ID ──
        while True:
            print()
            print(f"  {C_BOLD}步骤 2/3: Chat ID{C_RESET}")
            chat_id_raw = _read_input("请输入你的 Telegram Chat ID（纯数字）")
            if not chat_id_raw:
                _print_info("已取消配置")
                _read_input("按 Enter 返回")
                return
            if chat_id_raw.isdigit():
                chat_id = int(chat_id_raw)
                break
            _print_error("Chat ID 必须是纯数字，请重试")

        # ── 可选：操作员 chat_id ──
        print()
        operator_ids: list[int] = []
        while True:
            op_raw = _read_input(
                "输入额外的操作员 Chat ID（可选，直接按 Enter 跳过）"
            )
            if not op_raw:
                break
            if op_raw.isdigit():
                operator_ids.append(int(op_raw))
                _print_success(f"已添加操作员: {op_raw}")
            else:
                _print_error("Chat ID 必须是纯数字，已跳过")

        # ── 发送测试消息 ──
        print()
        print(f"  {C_BOLD}步骤 3/3: 验证 Bot Token{C_RESET}")
        _print_progress("正在发送测试消息到 Telegram")
        test_ok = self._test_telegram_token(token, chat_id)
        _print_done()

        if not test_ok:
            _print_error("测试消息发送失败！")
            print(f"  {C_YELLOW}  可能原因：{C_RESET}")
            print(f"  {C_DIM}  - Token 不正确或已过期{C_RESET}")
            print(f"  {C_DIM}  - Chat ID 不正确{C_RESET}")
            print(f"  {C_DIM}  - 需要先给 Bot 发送任意消息{C_RESET}")
            print(f"  {C_DIM}  - 网络不通，无法访问 Telegram API{C_RESET}")
            print()
            if not _confirm("是否仍然保存配置？（Token 无效时保存可能无法正常运行）"):
                _print_info("已取消保存")
                _read_input("按 Enter 返回")
                return

        else:
            _print_success("测试消息发送成功！请检查 Telegram 是否收到消息")

        # ── 保存配置 ──
        print()
        _print_progress("正在保存配置")
        try:
            from .config import save_config

            self._config.telegram.bot_token = token
            self._config.telegram.admin_chat_ids = [chat_id]
            self._config.telegram.operator_chat_ids = operator_ids
            self._config.telegram.notify_chat_id = chat_id
            self._config.config_path = self._config_path

            save_config(self._config, self._config_path)
            _print_done()
            _print_success(f"配置已保存到: {self._config_path}")
        except Exception as e:
            _print_error(f"保存配置失败: {e}")
            _read_input("按 Enter 返回")
            return

        # ── 是否立即重启服务 ──
        print()
        if _confirm("配置已更新，是否立即重启 f2b-manager 服务？"):
            _print_info("正在重启服务...")
            self._systemctl("restart", "f2b-manager")
            _print_success("服务已重启")
        else:
            _print_info("请稍后手动重启服务使配置生效")

        print()
        _read_input("按 Enter 返回主菜单")

    def _validate_token(self, token: str) -> bool:
        """验证 Bot Token 格式: 数字:字母数字串"""
        return bool(re.match(r"^\d+:[A-Za-z0-9_-]+$", token))

    def _test_telegram_token(self, token: str, chat_id: int) -> bool:
        """通过 httpx 调用 Telegram API 发送测试消息验证 Token"""
        try:
            import httpx

            url = (
                f"https://api.telegram.org/bot{token}/sendMessage"
                f"?chat_id={chat_id}"
                f"&text=f2b-manager%20%E9%85%8D%E7%BD%AE%E6%B5%8B%E8%AF%95%E2%9C%85"
            )
            with httpx.Client(timeout=15) as client:
                response = client.get(url)
                data = response.json()
                return data.get("ok", False)
        except Exception:
            return False

    # ── 5. 查看运行状态 ─────────────────────────

    def _menu_status(self) -> None:
        """查看 fail2ban 运行状态"""
        _print_header("Fail2ban 运行状态")

        if self._f2b_manager is None:
            _print_warning("Fail2ban 管理模块未就绪，尝试直接调用系统命令...")
            self._fallback_f2b_status()
            _read_input("按 Enter 返回")
            return

        try:
            status = self._f2b_manager.get_status()

            # 版本
            print(f"  {C_BOLD}版本:{C_RESET}   {status.version}")

            # 运行状态
            state_color = C_GREEN if status.state.value == "running" else C_RED
            state_icon = "● 运行中" if status.state.value == "running" else "○ 已停止"
            print(f"  {C_BOLD}状态:{C_RESET}   {state_color}{state_icon}{C_RESET}")

            # Jail 数量
            print(f"  {C_BOLD}Jail 数:{C_RESET} {status.jail_count}")

            # 总封禁数
            print(f"  {C_BOLD}总封禁:{C_RESET} {status.total_bans}")

            # 运行时长
            if status.uptime:
                print(f"  {C_BOLD}运行时长:{C_RESET} {status.uptime}")

            print()

            # 尝试获取 jail 详情
            try:
                jails = self._f2b_manager.get_jails()
                if jails:
                    print(f"  {C_BOLD}Jail 详情:{C_RESET}")
                    for jail in jails:
                        flag = f"{C_GREEN}✓{C_RESET}" if jail.enabled else f"{C_RED}✗{C_RESET}"
                        print(
                            f"    {flag} {C_BOLD}{jail.name}{C_RESET}  "
                            f"当前封禁: {C_YELLOW}{jail.current_ban}{C_RESET}  "
                            f"总封禁: {jail.total_banned}  "
                            f"总失败: {jail.total_failed}"
                        )
            except Exception as e:
                _print_warning(f"获取 jail 详情失败: {e}")

        except Exception as e:
            _print_error(f"获取状态失败: {e}")
            _print_info("提示: 请确认 fail2ban 已安装并运行")
            _print_info("可尝试: systemctl status fail2ban")

        print()
        _read_input("按 Enter 返回主菜单")

    def _fallback_f2b_status(self) -> None:
        """回退方式获取 fail2ban 状态（直接调用命令）"""
        try:
            from .utils.shell import run_command
            result = run_command("fail2ban-client status", timeout=10)
            if result.success:
                print(f"  {C_DIM}{result.stdout}{C_RESET}")
            else:
                _print_warning(f"fail2ban-client 不可用: {result.stderr}")
        except Exception as e:
            _print_error(f"无法获取状态: {e}")

    # ── 6. 查看封禁 IP 列表 ─────────────────────

    def _menu_banned_ips(self) -> None:
        """查看封禁 IP 列表（表格显示）"""
        _print_header("封禁 IP 列表")

        if self._f2b_manager is None:
            _print_warning("Fail2ban 管理模块未就绪，尝试直接调用系统命令...")
            try:
                from .utils.shell import run_command
                result = run_command("fail2ban-client banned", timeout=10)
                if result.success:
                    print(f"  {C_DIM}{result.stdout}{C_RESET}")
                else:
                    _print_error(f"fail2ban-client 不可用: {result.stderr}")
            except Exception as e:
                _print_error(f"获取封禁列表失败: {e}")
            _read_input("按 Enter 返回")
            return

        try:
            # 获取每个 jail 的详情
            jails = self._f2b_manager.get_jails()
            total_banned = 0

            if not jails:
                _print_info("没有启用的 jail，封禁列表为空")
                _read_input("按 Enter 返回")
                return

            # 表头
            print(f"  {C_BOLD}{'Jail':<16} {'IP 地址':<20} {'当前封禁':>8}  {'累计封禁':>8}{C_RESET}")
            print(f"  {C_DIM}{'─' * 16} {'─' * 20} {'─' * 8}  {'─' * 8}{C_RESET}")

            for jail_info in jails:
                try:
                    detail = self._f2b_manager.get_jail_status(jail_info.name)
                    if detail.banned_ips:
                        for ip in detail.banned_ips:
                            print(f"  {jail_info.name:<16} {C_RED}{ip:<20}{C_RESET} "
                                  f"{detail.current_ban:>8}  {detail.total_banned:>8}")
                            total_banned += 1
                    else:
                        print(f"  {jail_info.name:<16} {C_DIM}(空){C_RESET}")
                except Exception:
                    print(f"  {jail_info.name:<16} {C_DIM}(获取失败){C_RESET}")

            print(f"  {C_DIM}{'─' * 16} {'─' * 20} {'─' * 8}  {'─' * 8}{C_RESET}")
            print(f"  {C_BOLD}共 {total_banned} 个 IP 被封禁{C_RESET}")

        except Exception as e:
            _print_error(f"获取封禁列表失败: {e}")
            _print_info("提示: 请确认 fail2ban 已安装并运行")

        print()
        _read_input("按 Enter 返回主菜单")

    # ── 7. 手动封禁/解封 IP ─────────────────────

    def _menu_ban_manage(self) -> None:
        """手动封禁/解封 IP 子菜单"""
        while True:
            _print_header("IP 封禁管理")
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
        _print_header("手动封禁 IP")

        if self._f2b_manager is None:
            _print_error("Fail2ban 管理模块未就绪")
            _read_input("按 Enter 返回")
            return

        # 输入 IP
        while True:
            ip = _read_input("请输入要封禁的 IP 地址（如 192.168.1.100）")
            if not ip:
                _print_info("已取消")
                _read_input("按 Enter 返回")
                return
            if self._validate_ip(ip):
                break
            _print_error("IP 地址格式不正确，请输入有效 IPv4 地址")

        # 输入 jail（可选）
        jail = _read_input("请输入 jail 名称（默认: sshd）", "sshd")

        print()
        print(f"  {C_YELLOW}即将封禁: IP={ip}, Jail={jail}{C_RESET}")
        if not _confirm("确认执行封禁？"):
            _print_info("已取消")
            _read_input("按 Enter 返回")
            return

        print()
        _print_progress(f"正在封禁 {ip}")
        try:
            success = self._f2b_manager.ban_ip(ip, jail)
            if success:
                _print_done()
                _print_success(f"IP {ip} 已在 jail '{jail}' 中封禁")
            else:
                _print_error(f"封禁 {ip} 失败")
        except Exception as e:
            _print_error(f"封禁过程发生错误: {e}")

        print()
        _read_input("按 Enter 继续")

    def _menu_unban_ip(self) -> None:
        """解封 IP 子流程"""
        _print_header("手动解封 IP")

        if self._f2b_manager is None:
            _print_error("Fail2ban 管理模块未就绪")
            _read_input("按 Enter 返回")
            return

        # 输入 IP
        while True:
            ip = _read_input("请输入要解封的 IP 地址")
            if not ip:
                _print_info("已取消")
                _read_input("按 Enter 返回")
                return
            if self._validate_ip(ip):
                break
            _print_error("IP 地址格式不正确，请输入有效 IPv4 地址")

        print()
        print(f"  {C_YELLOW}即将解封: IP={ip}{C_RESET}")
        if not _confirm("确认执行解封？"):
            _print_info("已取消")
            _read_input("按 Enter 返回")
            return

        print()
        _print_progress(f"正在解封 {ip}")
        try:
            success = self._f2b_manager.unban_ip(ip)
            if success:
                _print_done()
                _print_success(f"IP {ip} 已解封")
            else:
                _print_error(f"解封 {ip} 失败")
        except Exception as e:
            _print_error(f"解封过程发生错误: {e}")

        print()
        _read_input("按 Enter 继续")

    @staticmethod
    def _validate_ip(ip: str) -> bool:
        """校验 IPv4 地址格式"""
        try:
            ipaddress.IPv4Address(ip)
            return True
        except (ipaddress.AddressValueError, ValueError):
            return False

    # ── 8. 服务控制 ──────────────────────────────

    def _menu_service_control(self) -> None:
        """启动 / 停止 / 重启服务 子菜单"""
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
                self._show_service_status()
            elif choice == 7:
                break

            print()
            _read_input("按 Enter 继续")

    def _systemctl(self, action: str, service: str) -> None:
        """执行 systemctl 命令并显示结果"""
        _print_progress(f"systemctl {action} {service}")
        try:
            from .utils.shell import run_command
            result = run_command(
                f"systemctl {action} {service}", timeout=30
            )
            if result.success:
                _print_done()
                _print_success(f"服务 {service}: {action} 成功")
            else:
                _print_error(f"操作失败: {result.stderr[:200]}")
        except Exception as e:
            _print_error(f"执行失败: {e}")

    def _show_service_status(self) -> None:
        """查看 f2b-manager 和 fail2ban 服务状态"""
        print()
        for service in ("f2b-manager", "fail2ban"):
            try:
                from .utils.shell import run_command
                result = run_command(
                    f"systemctl is-active {service}", timeout=10
                )
                active = result.stdout.strip()
                color = C_GREEN if active == "active" else C_RED
                icon = "● 运行中" if active == "active" else "○ 已停止"
                print(f"  {C_BOLD}{service}:{C_RESET} {color}{icon}{C_RESET}")

                # 显示更多状态
                status_result = run_command(
                    f"systemctl status {service} --no-pager -l --lines=0",
                    timeout=10,
                )
                if status_result.success:
                    # 提取关键行
                    for line in status_result.stdout.split("\n"):
                        line = line.strip()
                        if any(kw in line for kw in ("Active:", "Loaded:", "Main PID:")):
                            print(f"    {C_DIM}{line}{C_RESET}")
            except Exception:
                print(f"  {C_BOLD}{service}:{C_RESET} {C_DIM}无法获取状态{C_RESET}")

            print()

    # ── 9. 查看日志 ──────────────────────────────

    def _menu_view_logs(self) -> None:
        """查看最近日志"""
        _print_header("查看日志")

        lines = _read_input("显示最近多少行（默认 50）", "50")
        try:
            n_lines = int(lines)
        except ValueError:
            n_lines = 50

        print()
        print(f"  {C_DIM}最近 {n_lines} 行日志:{C_RESET}")
        _print_separator()

        try:
            from .utils.shell import run_command
            result = run_command(
                f"journalctl -u f2b-manager --no-pager -n {n_lines}",
                timeout=10,
            )
            if result.success:
                for line in result.stdout.split("\n"):
                    # 根据日志级别着色
                    if "ERROR" in line or "error" in line.lower():
                        print(f"  {C_RED}{line}{C_RESET}")
                    elif "WARN" in line or "warning" in line.lower():
                        print(f"  {C_YELLOW}{line}{C_RESET}")
                    else:
                        print(f"  {C_DIM}{line}{C_RESET}")
            else:
                if "No journal files" in result.stderr or "No entries" in result.stderr:
                    _print_info("暂无日志记录（服务可能尚未运行）")
                else:
                    _print_warning(f"读取日志失败: {result.stderr[:200]}")
        except Exception as e:
            _print_error(f"读取日志失败: {e}")

        _print_separator()
        print()
        _read_input("按 Enter 返回主菜单")


# ── 命令行直接运行（调试用）──────────────────────
if __name__ == "__main__":
    menu = InteractiveMenu()
    menu.run()
