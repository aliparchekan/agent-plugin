# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""把 scripts/ 加入 sys.path，供测试直接 import 工具链模块。"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PLUGIN_DIR = REPO_ROOT / "plugins" / "example-plugin"
