"""pytest 配置：把 apps/api 加入 sys.path，使 `app` 包可导入。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
