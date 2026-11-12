"""pytest 配置：把 apps/api 加入 sys.path，使 `app` 包可导入。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _isolate_vocab_log(tmp_path, monkeypatch):
    """测试作答不写入真实日志，避免污染 data/logs/vocab_sessions.jsonl。

    见 issue #43：标定依赖这份日志，测试产生的会话必须隔离。
    """
    from app.config import settings

    monkeypatch.setattr(
        settings, "vocab_log_path", str(tmp_path / "vocab_sessions.jsonl")
    )
