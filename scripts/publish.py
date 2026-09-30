#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Hub publisher — 校验、打包并上传插件包到 swarmskills Hub。

上传协议对齐 jiuwenswarm 主仓 ``hub_publish_client.py``：
``POST {base_url}/api/v1/plugins``，multipart 字段 asset_name / plugin_version /
display_name / description / tags / version_desc / visibility / force（+ 可选
plugin_id），文件字段 file=asset.zip，请求头带 Bearer token 与 X-Checksum-SHA256。

凭据来自环境变量（不落任何文件）：
    JIUWENSWARM_HUB_TOKEN     必填，发布访问令牌
    JIUWENSWARM_HUB_BASE_URL  可选，默认 https://swarmskills.openjiuwen.com

Usage:
    publish.py example-plugin            # 校验 + 打包 + 上传
    publish.py example-plugin --force    # 同版本强制覆盖（谨慎）
    publish.py example-plugin --private  # 以 private 可见性上传
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
PLUGINS_DIR = REPO_ROOT / "plugins"
DEFAULT_BASE_URL = "https://swarmskills.openjiuwen.com"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

TOKEN_RE = re.compile(r"[!-~]+")

# 与主仓 hub_asset_type_adapter 的 plugin 契约一致
_ACCEPTED_HUB_TYPES = frozenset({"agent-plugin", "plugin"})
# publish_result 中允许 visibility 为 null 的受理态（对齐主仓 parse_publish_result）
_VISIBILITY_UNCONFIRMED_STATES = frozenset(
    {"pending_moderation", "publish_success", "published", "publish_failed"}
)


def write_stdout(text: str) -> None:
    os.write(1, text.encode("utf-8"))


class PublishError(RuntimeError):
    pass


def _validate_hub_result(
    payload: object,
    *,
    expect_name: str,
    expect_version: str,
    expect_visibility: str,
) -> dict:
    """校验 Hub 业务响应（对齐主仓 parse_publish_result 的 plugin 分支）。

    业务失败、协议异常或返回资产与请求不一致时抛 PublishError；
    通过时返回 data 字典（含 asset_id / publish_result / visibility 等）。
    """
    if not isinstance(payload, dict) or payload.get("code") != 200:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("message") or payload.get("code") or payload)[:200]
        raise PublishError(f"Hub 业务校验失败（code != 200）: {detail}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise PublishError("Hub 响应缺少 data 资产信息")

    types = [data[key] for key in ("asset_type", "plugin_type") if key in data]
    if not types or any(t not in _ACCEPTED_HUB_TYPES for t in types):
        raise PublishError(f"Hub 返回的资产类型异常: {types}")
    asset_id = data.get("asset_id") or data.get("plugin_id")
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise PublishError("Hub 响应缺少 asset_id / plugin_id")
    for key in ("asset_id", "plugin_id"):
        if key in data and data[key] != asset_id:
            raise PublishError("Hub 返回的 asset_id 与 plugin_id 冲突")
    if data.get("name") != expect_name or data.get("version") != expect_version:
        raise PublishError(
            "Hub 返回资产与请求不一致: "
            f"{data.get('name')}@{data.get('version')}（期望 {expect_name}@{expect_version}）"
        )
    state = data.get("publish_result")
    if state is not None and not isinstance(state, str):
        raise PublishError("Hub 返回的 publish_result 非法")
    visibility = data.get("visibility")
    unconfirmed = visibility is None and state in _VISIBILITY_UNCONFIRMED_STATES
    if not unconfirmed and visibility not in ("public", "private"):
        raise PublishError(f"Hub 返回的可见性非法: {visibility!r}")
    if visibility is not None and visibility != expect_visibility:
        raise PublishError(
            f"Hub 返回可见性 {visibility} 与请求 {expect_visibility} 不一致"
        )
    if state == "publish_failed":
        raise PublishError("Hub 报告发布失败（publish_result=publish_failed）")
    return data


def _run(cmd: list[str]) -> None:
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        raise PublishError(f"前置步骤失败: {' '.join(cmd)}")


def _read_manifest(pkg_dir: Path) -> dict:
    import json

    return json.loads((pkg_dir / "manifest.json").read_text(encoding="utf-8"))


def upload(
    zip_path: Path,
    *,
    base_url: str,
    token: str,
    plugin_id: str,
    version: str,
    display_name: str,
    description: str,
    tags: str,
    visibility: str,
    force: bool,
) -> dict:
    """流式风格改为一次性读入（仓库脚本包体 ≤50MB），字段协议与主仓一致。"""
    body = zip_path.read_bytes()
    sha256 = hashlib.sha256(body).hexdigest()

    fields = {
        "asset_name": plugin_id,
        "plugin_version": version,
        "display_name": display_name,
        "description": description,
        "tags": tags,
        "version_desc": "Published from openJiuwen/agent-plugin repository",
        "visibility": visibility,
        "force": "true" if force else "false",
    }

    boundary = secrets.token_hex(24)
    parts = [
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")
        for name, value in fields.items()
    ]
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="asset.zip"\r\nContent-Type: application/zip\r\n\r\n'
        ).encode("utf-8")
    )
    parts.append(body)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    payload = b"".join(parts)

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/plugins",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Checksum-SHA256": sha256,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise PublishError("响应体过大，拒绝解析")
            import json

            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise PublishError(
                    f"Hub 响应不是合法 JSON（HTTP {response.status}）: "
                    f"{raw[:200].decode('utf-8', 'replace')}"
                ) from None
            return _validate_hub_result(
                payload,
                expect_name=plugin_id,
                expect_version=version,
                expect_visibility=visibility,
            )
    except urllib.error.HTTPError as exc:
        detail = exc.read(MAX_RESPONSE_BYTES)
        raise PublishError(
            f"Hub 拒绝上传：HTTP {exc.code} {detail[:500].decode('utf-8', 'replace')}"
        ) from exc
    except urllib.error.URLError as exc:
        raise PublishError(f"无法连接 Hub（{base_url}）: {exc.reason}") from exc


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="校验、打包并上传插件包到 Hub")
    parser.add_argument("target", help="插件包名（plugins/ 下）")
    parser.add_argument("--force", action="store_true", help="同版本强制覆盖")
    parser.add_argument("--private", action="store_true", help="以 private 可见性上传")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("JIUWENSWARM_HUB_BASE_URL", DEFAULT_BASE_URL),
        help=f"Hub 地址（默认 {DEFAULT_BASE_URL}）",
    )
    parser.add_argument("--skip-validate", action="store_true", help="跳过前置校验（不推荐）")
    args = parser.parse_args()

    token = os.environ.get("JIUWENSWARM_HUB_TOKEN", "").strip()
    if not token or not TOKEN_RE.fullmatch(token):
        write_stdout("Error: 缺少或非法 JIUWENSWARM_HUB_TOKEN 环境变量\n")
        return 1

    pkg_dir = PLUGINS_DIR / args.target
    if not pkg_dir.is_dir():
        write_stdout(f"Error: 找不到插件包目录: {args.target}\n")
        return 1

    try:
        if not args.skip_validate:
            write_stdout("==> [1/3] 校验（L0/L1 + 热加载尽力执行）\n")
            _run([sys.executable, str(SCRIPTS_DIR / "validate.py"), args.target])

        write_stdout("==> [2/3] 打包\n")
        dist_dir = REPO_ROOT / "dist"
        _run([sys.executable, str(SCRIPTS_DIR / "build.py"), args.target])

        manifest = _read_manifest(pkg_dir)
        display = manifest.get("display_name") or {}
        tags = manifest.get("tags") or []
        tag_names = [
            str(t.get("zh") or t.get("en")) for t in tags if isinstance(t, dict)
        ]
        zip_path = dist_dir / (
            f"{manifest.get('id')}-{manifest.get('version')}.zip"
        )
        if not zip_path.is_file():
            raise PublishError(f"打包产物不存在: {zip_path}")

        write_stdout(f"==> [3/3] 上传到 {args.base_url}\n")
        result = upload(
            zip_path,
            base_url=args.base_url,
            token=token,
            plugin_id=str(manifest.get("id")),
            version=str(manifest.get("version")),
            display_name=str(display.get("zh") or display.get("en") or ""),
            description=str(manifest.get("description") or ""),
            tags=",".join(tag_names),
            visibility="private" if args.private else "public",
            force=args.force,
        )
        state = result.get("publish_result")
        asset_id = result.get("asset_id") or result.get("plugin_id")
        write_stdout(f"Hub 已确认资产: {asset_id}（{args.target}@{manifest.get('version')}）\n")
        if state == "pending_moderation":
            write_stdout("上传已受理，等待 Hub 审核（pending_moderation）。\n")
        else:
            write_stdout("发布完成。回滚方式见 docs/hub-publish.md\n")
        return 0
    except PublishError as exc:
        write_stdout(f"Error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
