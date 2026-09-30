#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""L2 hot-load worker for plugin packages — runs in a dedicated subprocess.

加载链对齐 jiuwenswarm 运行时（openjiuwen.harness.manifest.meta_elements
的 ``_load_class_from_file``）：组件以获得 canonical 包模块名
``openjiuwen.extensions.harness.<pkg>.<rel>`` 的方式加载，并临时注入
合成父包与 sys.path 条目，使包内相对导入（``from .helper import VALUE``）
与同目录绝对导入与运行时行为一致；但不拉起完整 harness。完整 harness
冒烟仍在 jiuwenswarm 主仓 plugin-creator 的 validate_plugin.py --hot-load 中执行。

Prints one JSON object on the last stdout line for the parent controller.

Exit codes:
    0  pass
    1  fail (package load/instantiate errors)
    2  skip (environment / import problems)
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

RAIL_HOOK_METHODS = (
    "before_invoke",
    "after_invoke",
    "before_model_call",
    "after_model_call",
    "before_tool_call",
    "after_tool_call",
    "before_task_iteration",
    "after_task_iteration",
)

# 与运行时 _canonical_extension_module_name 一致的命名空间前缀
_HARNESS_NAMESPACE = "openjiuwen.extensions.harness"


def write_stdout(text: str) -> None:
    """product output to fd 1."""
    os.write(1, text.encode("utf-8"))


def _result(
    status: str,
    *,
    errors: list[list[str]] | None = None,
    notes: list[str] | None = None,
    skip_reason: str = "",
    skip_fix: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "errors": errors or [],
        "notes": notes or [],
        "skip_reason": skip_reason,
        "skip_fix": skip_fix,
    }


def _ensure_package_namespace(pkg: Path) -> str:
    """建立合成父包（__path__ 指向包根），让包内相对导入可解析。

    对齐运行时 _temporary_extension_alias：进程级一次性设置（worker 是
    一次性子进程，无需快照/回滚）。
    """
    package_name = f"{_HARNESS_NAMESPACE}.{pkg.name}"
    harness = sys.modules.get(_HARNESS_NAMESPACE)
    if harness is None:
        harness = ModuleType(_HARNESS_NAMESPACE)
        harness.__path__ = [str(pkg.parent)]  # type: ignore[attr-defined]
        sys.modules[_HARNESS_NAMESPACE] = harness
    package = sys.modules.get(package_name)
    if package is None:
        package = ModuleType(package_name)
        package.__path__ = [str(pkg)]  # type: ignore[attr-defined]
        sys.modules[package_name] = package
        setattr(harness, pkg.name, package)
    return package_name


def _load_module(pkg: Path, rel_file: str, package_name: str):
    """按运行时的 importlib spec 方式加载包内模块（含包命名空间）。"""
    pkg_root = pkg.resolve()
    file_path = (pkg_root / rel_file).resolve()
    if not file_path.is_relative_to(pkg_root) or not file_path.is_file():
        raise ValueError(f"文件不存在或越出包根目录: {rel_file}")
    dotted = ".".join(file_path.relative_to(pkg_root).with_suffix("").parts)
    module_name = f"{package_name}.{dotted}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"无法创建模块加载 spec: {rel_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    # 对齐运行时 _temporary_sys_path(path.parent, path.parent.parent)：
    # 支持同目录绝对导入（import helper）
    added: list[str] = []
    for entry in (str(file_path.parent), str(pkg_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
            added.append(entry)
    before = set(sys.modules)
    try:
        spec.loader.exec_module(module)
    finally:
        for entry in added:
            sys.path.remove(entry)
        # 回收经临时路径载入的包内顶层模块，避免同包不同子目录的同名模块串扰
        for name in set(sys.modules) - before:
            if name == module_name or name.startswith(f"{package_name}."):
                continue
            loaded = sys.modules.get(name)
            loaded_file = getattr(loaded, "__file__", None)
            if loaded_file and Path(loaded_file).resolve().is_relative_to(pkg_root):
                sys.modules.pop(name, None)
    return module


def _check_tool_instance(instance: Any, class_name: str, notes: list[str]) -> None:
    from openjiuwen.core.foundation.tool import Tool

    if not isinstance(instance, Tool):
        raise TypeError(f"{class_name} 实例不是 Tool（继承链断裂或基类不匹配）")
    notes.append(f"tool {class_name}: 无参实例化成功")


def _check_rail_instance(instance: Any, class_name: str, notes: list[str]) -> None:
    from openjiuwen.harness.rails.base import DeepAgentRail

    if not isinstance(instance, DeepAgentRail):
        raise TypeError(f"{class_name} 实例不是 DeepAgentRail（继承链断裂或基类不匹配）")
    hooks = [
        name
        for name in RAIL_HOOK_METHODS
        if callable(getattr(instance, name, None))
        and getattr(type(instance), name, None) is not getattr(DeepAgentRail, name, None)
    ]
    if not hooks:
        raise ValueError(
            f"{class_name} 未实现任何生命周期钩子（{'/'.join(RAIL_HOOK_METHODS[:4])}… 至少其一）"
        )
    notes.append(f"rail {class_name}: 无参实例化成功，钩子: {', '.join(hooks)}")


def run(pkg: Path) -> dict[str, Any]:
    try:
        import openjiuwen  # noqa: F401 — 探测运行时可用性
    except Exception as exc:  # noqa: BLE001 — 任何导入失败都按环境问题跳过
        return _result(
            "skip",
            skip_reason=f"openjiuwen 运行时不可用（{exc}）",
            skip_fix=(
                "在 jiuwenswarm 运行环境执行（主仓 .venv），"
                "或安装 openjiuwen 后重跑"
            ),
        )

    manifest_path = pkg / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _result("fail", errors=[[f"manifest.json 读取失败: {exc}", ""]])

    errors: list[list[str]] = []
    notes: list[str] = []
    checked = 0
    package_name = _ensure_package_namespace(pkg)

    for field, checker in (("tools", _check_tool_instance), ("rails", _check_rail_instance)):
        for idx, item in enumerate(manifest.get(field) or []):
            if not isinstance(item, dict):
                continue
            rel_file = str(item.get("file") or "")
            class_name = str(item.get("class") or "")
            checked += 1
            try:
                module = _load_module(pkg, rel_file, package_name)
                cls = getattr(module, class_name, None)
                if cls is None:
                    raise AttributeError(
                        f"模块 {rel_file} 中不存在类 {class_name!r}"
                    )
                instance = cls()
                checker(instance, class_name, notes)
            except Exception as exc:  # noqa: BLE001 — 单个组件失败不阻断其余检查
                errors.append(
                    [
                        f"{field}[{idx}] ({rel_file}#{class_name}) 加载失败: {exc}",
                        "修复 import / 继承 / 无参构造错误后重跑",
                    ]
                )

    if errors:
        return _result("fail", errors=errors, notes=notes)
    if checked == 0:
        notes.append("包内没有声明 tools / rails，无代码组件需要热加载")
    return _result("pass", notes=notes)


def main() -> int:
    if len(sys.argv) != 2:
        write_stdout(json.dumps(_result("skip", skip_reason="usage: hot_load_worker.py <pkg>")))
        return 2
    pkg = Path(sys.argv[1]).expanduser().resolve()
    if not pkg.is_dir():
        write_stdout(json.dumps(_result("skip", skip_reason=f"目录不存在: {pkg}")))
        return 2

    result = run(pkg)
    write_stdout(json.dumps(result, ensure_ascii=False) + "\n")
    status = str(result.get("status"))
    return {"pass": 0, "fail": 1}.get(status, 2)


if __name__ == "__main__":
    raise SystemExit(main())
