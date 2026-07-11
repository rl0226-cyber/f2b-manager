"""
f2b_manager.utils.shell
=======================

subprocess 封装，提供安全的命令执行接口。
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class CommandResult:
    """命令执行结果"""
    returncode: int
    stdout: str
    stderr: str
    success: bool

    @property
    def output(self) -> str:
        """合并 stdout + stderr"""
        return (self.stdout + self.stderr).strip()


def run_command(
    cmd: str | list[str],
    *,
    timeout: int = 120,
    check: bool = False,
    input_text: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> CommandResult:
    """执行 shell 命令

    Args:
        cmd: 命令字符串或参数列表
        timeout: 超时秒数
        check: 为 True 时非零退出码抛出 CalledProcessError
        input_text: 传给 stdin 的文本
        env: 额外环境变量

    Returns:
        CommandResult
    """
    if isinstance(cmd, str):
        args = shlex.split(cmd)
    else:
        args = list(cmd)

    full_env = None
    if env:
        import os
        full_env = os.environ.copy()
        full_env.update(env)

    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
        env=full_env,
    )

    result = CommandResult(
        returncode=proc.returncode,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
        success=(proc.returncode == 0),
    )

    if check and not result.success:
        raise subprocess.CalledProcessError(
            proc.returncode, args, proc.stdout, proc.stderr
        )

    return result


def which(binary: str) -> Optional[str]:
    """检查命令是否存在，返回完整路径"""
    result = run_command(f"which {binary}", timeout=5)
    return result.stdout if result.success else None
