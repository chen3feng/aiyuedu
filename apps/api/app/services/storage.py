"""JSON 文件原子落盘。

所有整文件改写（collection、users、config 等）都走 ``atomic_write_json``：
先写同目录唯一临时文件 → flush + fsync → ``os.replace`` 原子改名。
相比直接 ``open(path, "w")``：

- 写到一半进程崩溃 / 磁盘满时，旧文件完好，不会留下被截断的 JSON；
- ``os.replace`` 在同文件系统内是原子的，并发读到的要么是旧版要么是新版；
- 临时名带随机后缀，同进程多线程 / 多进程并发写不会互踩临时文件。

注意：它只保证「单次写入」原子。「读 → 改 → 写」序列的并发安全仍需调用方
自己加锁（见 collections._lock）。
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


def atomic_write_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        # 写失败时清掉半成品临时文件；replace 之后这里不会再执行
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_json_or(path: str | Path, default: Any | Callable[[], Any]) -> Any:
    """读 JSON；文件不存在 / 损坏 / OSError 时返回默认值。

    ``default`` 可以是值，也可以是零参工厂（避免共享同一个可变默认）。
    替代各模块里重复了 8 次的 ``try: json.loads(read_text) except: return {}``。
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default() if callable(default) else default
