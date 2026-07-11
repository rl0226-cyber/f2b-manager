"""
f2b_manager.utils.logger
========================

日志配置。

提供带文件轮转的日志器，控制台 + 文件双输出。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# 日志格式
_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# 已配置标记，避免重复初始化
_initialized = False


def setup_logging(
    level: str = "INFO",
    log_file: str = "/var/log/f2b-manager.log",
    max_size_mb: int = 10,
    backup_count: int = 5,
) -> logging.Logger:
    """初始化全局日志配置

    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_file: 日志文件路径
        max_size_mb: 单文件最大 MB
        backup_count: 保留备份数

    Returns:
        配好的根日志器
    """
    global _initialized

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if _initialized:
        return root_logger

    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件输出（带轮转）
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_size_mb * 1024 * 1024,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except (PermissionError, OSError):
            # 无权限写日志文件（非 root 运行），仅控制台输出
            root_logger.warning(f"无法写入日志文件 {log_file}，仅控制台输出")

    _initialized = True
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器"""
    return logging.getLogger(name)
