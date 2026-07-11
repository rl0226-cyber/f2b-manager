"""utils 包：通用工具（shell/distro/logger）"""

from .shell import CommandResult, run_command, which
from .distro import (
    detect_distro, get_install_command, get_remove_command,
    get_upgrade_command,
)
from .logger import get_logger, setup_logging

__all__ = [
    "CommandResult", "run_command", "which",
    "detect_distro", "get_install_command", "get_remove_command",
    "get_upgrade_command",
    "get_logger", "setup_logging",
]
