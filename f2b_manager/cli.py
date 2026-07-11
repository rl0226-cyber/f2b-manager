"""
f2b_manager.cli
===============

命令行入口。

支持子命令:
  f2b-manager run                 启动守护进程（Bot + Scheduler）
  f2b-manager fail2ban install    安装 fail2ban
  f2b-manager fail2ban uninstall  卸载 fail2ban
  f2b-manager fail2ban update     更新 fail2ban
  f2b-manager notify              发送通知（供 notify.sh 调用）
  f2b-manager status              查看 fail2ban 状态
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from .config import AppConfig, load_config


class _CliBotSender:
    """轻量 Telegram 消息发送器，仅用于 CLI notify 命令。

    直接使用 telegram.Bot(token=...) 调用 Bot API，不引入
    ApplicationBuilder / polling / job_queue 等额外开销。
    实现 IMessageSender 协议中 CLI 路径需要的 send_alert 方法。
    """

    def __init__(self, token: str):
        from telegram import Bot
        from telegram.error import Forbidden, NetworkError, TelegramError
        self._bot = Bot(token=token)
        self._logger = logging.getLogger("cli.bot_sender")
        # 保存异常类引用，便于测试 mock
        self._Forbidden = Forbidden
        self._NetworkError = NetworkError
        self._TelegramError = TelegramError

    async def send_alert(self, chat_id: int, message: str,
                         parse_mode: str = "HTML") -> bool:
        """发送预警消息到指定 chat_id。

        与 F2BTelegramBot.send_alert() 行为一致：Forbidden 只记 warning，
        网络/API 错误记 error，统一返回 bool。
        """
        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            return True
        except self._Forbidden:
            self._logger.warning("用户 %d 已屏蔽 Bot，无法发送预警", chat_id)
            return False
        except self._NetworkError as e:
            self._logger.error("发送预警消息网络错误: %s", e)
            return False
        except self._TelegramError as e:
            self._logger.error("发送预警消息失败: %s", e)
            return False

    async def send_report(self, chat_id: int, message: str) -> bool:
        """CLI 路径不需要 send_report，仅满足 IMessageSender 协议。"""
        self._logger.debug("send_report 在 CLI 模式下不支持")
        return False


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        prog="f2b-manager",
        description="VPS Fail2ban 管理系统 - Telegram 机器人 + 实时预警",
    )
    parser.add_argument(
        "-c", "--config",
        default=None,
        help="配置文件路径 (默认: /etc/f2b-manager/config.yaml)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细输出 (DEBUG 日志)",
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # run: 启动守护进程
    run_parser = subparsers.add_parser("run", help="启动守护进程")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅检查配置，不实际启动",
    )

    # fail2ban: 管理 fail2ban
    f2b_parser = subparsers.add_parser("fail2ban", help="管理 fail2ban")
    f2b_sub = f2b_parser.add_subparsers(dest="fail2ban_action")
    f2b_sub.add_parser("install", help="安装 fail2ban")
    uninstall_parser = f2b_sub.add_parser("uninstall", help="卸载 fail2ban")
    uninstall_parser.add_argument(
        "--purge-config",
        action="store_true",
        help="同时删除配置文件",
    )
    f2b_sub.add_parser("update", help="更新 fail2ban")

    # notify: 发送通知（供 notify.sh 调用）
    notify_parser = subparsers.add_parser("notify", help="发送通知")
    notify_parser.add_argument("--event", required=True, help="事件类型: ban/unban/start/stop")
    notify_parser.add_argument("--ip", default="", help="IP 地址")
    notify_parser.add_argument("--jail", default="", help="jail 名称")
    notify_parser.add_argument("--failures", default="0", help="失败次数")
    notify_parser.add_argument("--matches", default="", help="匹配的日志")

    # status: 查看状态
    subparsers.add_parser("status", help="查看 fail2ban 状态")

    # menu: 交互式管理菜单
    subparsers.add_parser("menu", help="交互式管理菜单")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 主入口"""
    parser = build_parser()
    args = parser.parse_args(argv)

    # 加载配置
    config = load_config(args.config)

    # 日志级别
    log_level = "DEBUG" if args.verbose else config.logging.level
    from .utils.logger import setup_logging
    setup_logging(
        level=log_level,
        log_file=config.logging.file,
        max_size_mb=config.logging.max_size_mb,
        backup_count=config.logging.backup_count,
    )

    logger = __import__("logging").getLogger("cli")

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "run":
        return _cmd_run(config, args)

    if args.command == "fail2ban":
        return _cmd_fail2ban(config, args)

    if args.command == "notify":
        return _cmd_notify(config, args)

    if args.command == "status":
        return _cmd_status(config, args)

    if args.command == "menu":
        return _cmd_menu(config, args)

    parser.print_help()
    return 0


def _cmd_run(config, args) -> int:
    """启动守护进程"""
    logger = __import__("logging").getLogger("run")

    # 校验配置
    errors = config.validate()
    if errors:
        for e in errors:
            logger.error(f"配置错误: {e}")
        logger.error("请编辑配置文件后重试")
        return 1

    logger.info("配置校验通过")

    if args.dry_run:
        logger.info("--dry-run 模式，不实际启动")
        return 0

    # 启动应用（后续 Wave 实现）
    logger.info("启动 f2b-manager 守护进程...")
    try:
        from .app import Application
        app = Application(config)
        app.run()
    except ImportError:
        logger.warning("应用主类尚未实现（Wave 2+ 完成）")
        logger.info("M0 基础设施已就绪，请继续 Wave 2 开发")
        return 0
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出")
        return 0

    return 0


def _cmd_fail2ban(config, args) -> int:
    """管理 fail2ban"""
    logger = __import__("logging").getLogger("fail2ban")

    action = args.fail2ban_action
    if not action:
        logger.error("请指定操作: install / uninstall / update")
        return 1

    try:
        from .fail2ban.installer import Fail2banInstaller
        installer = Fail2banInstaller(config)
    except ImportError:
        logger.warning("Fail2ban 管理模块尚未实现（Wave 2 M1）")
        return 0

    if action == "install":
        result = installer.install()
    elif action == "uninstall":
        result = installer.uninstall(keep_config=not args.purge_config)
    elif action == "update":
        result = installer.update()
    else:
        logger.error(f"未知操作: {action}")
        return 1

    if result.success:
        logger.info(f"操作成功: {result.message}")
    else:
        logger.error(f"操作失败: {result.message}")
        for d in result.details:
            logger.error(f"  {d}")

    return 0 if result.success else 1


def _cmd_notify(config, args) -> int:
    """发送通知（供 notify.sh 调用）

    由 fail2ban action 触发，通过 CLI 子命令将事件转发给守护进程的
    预警模块处理。此处为独立 CLI 模式（非守护进程），直接创建
    AlertSender 实例处理事件后退出。
    """
    logger = __import__("logging").getLogger("notify")

    import asyncio

    from .notify.sender import AlertSender
    from .storage.database import StateDB
    from .storage.models import BanAction, BanEvent

    try:
        action = BanAction(args.event)
    except ValueError:
        logger.error(f"未知事件类型: {args.event}")
        return 1

    event = BanEvent(
        ip=args.ip,
        jail=args.jail,
        action=action,
        failures=int(args.failures) if args.failures else 0,
        matches=args.matches,
    )

    logger.info(f"收到通知事件: {action.value} ip={args.ip} jail={args.jail} "
                f"failures={args.failures}")

    # 初始化状态库（用于记录事件）
    db = None
    try:
        db = StateDB(db_path=config.database.path)
    except Exception as e:
        logger.warning(f"无法初始化状态库: {e}，事件将不记录")

    # 创建消息发送器：有 bot_token 时构造轻量 _CliBotSender，
    # 否则保持 None（仅记录不发送，并打印 warning 日志）
    if config.telegram.bot_token:
        bot = _CliBotSender(config.telegram.bot_token)
        logger.info("已构造 Telegram 消息发送器，预警将通过 Bot API 发送")
    else:
        bot = None
        logger.warning(
            "未配置 telegram.bot_token，预警消息将仅记录到数据库，"
            "不会发送到 Telegram。请在配置文件中设置 bot_token 以启用实时预警。"
        )

    sender = AlertSender(config=config, bot=bot, db=db)

    try:
        # 根据事件类型分发处理
        if action in (BanAction.BAN, BanAction.UNBAN):
            result = asyncio.run(sender.send_ban_alert(event))
        elif action in (BanAction.START, BanAction.STOP):
            result = asyncio.run(
                sender.send_service_alert(action, jail=args.jail)
            )
        else:
            logger.error(f"不支持的事件类型: {action}")
            result = False
    except Exception as e:
        logger.error(f"处理通知事件失败: {e}", exc_info=True)
        result = False
    finally:
        sender.close()
        if db is not None:
            db.close()

    return 0 if result else 1


def _cmd_status(config, args) -> int:
    """查看 fail2ban 状态"""
    logger = __import__("logging").getLogger("status")

    try:
        from .fail2ban.manager import Fail2banManager
        manager = Fail2banManager()
        status = manager.get_status()
        print(f"版本: {status.version}")
        print(f"状态: {status.state.value}")
        print(f"Jail 数: {status.jail_count}")
        print(f"总封禁: {status.total_bans}")
    except ImportError:
        logger.warning("Fail2ban 管理模块尚未实现（Wave 2 M1）")
        # 回退：直接调用系统命令
        from .utils.shell import run_command
        result = run_command("fail2ban-client status", timeout=10)
        if result.success:
            print(result.stdout)
        else:
            print(f"fail2ban-client 不可用: {result.stderr}")
            return 1

    return 0


def _cmd_menu(config, args) -> int:
    """启动交互式管理菜单"""
    try:
        from .menu import InteractiveMenu
        menu = InteractiveMenu(config_path=config.config_path or "/etc/f2b-manager/config.yaml")
        menu.run()
        return 0
    except ImportError:
        logger = __import__("logging").getLogger("menu")
        logger.error("交互式菜单模块加载失败")
        return 1
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
