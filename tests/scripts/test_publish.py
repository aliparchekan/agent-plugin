# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""publish.py 单测：Hub 业务响应校验（对齐主仓 parse_publish_result 的 plugin 分支）。"""

from __future__ import annotations

import pytest

import publish

EXPECT = {
    "expect_name": "example-plugin",
    "expect_version": "1.0.0",
    "expect_visibility": "public",
}


def _ok_payload(**overrides) -> dict:
    data = {
        "plugin_type": "agent-plugin",
        "plugin_id": "plg-123",
        "name": "example-plugin",
        "version": "1.0.0",
        "publish_result": "publish_success",
        "visibility": "public",
        "deduplicated": False,
    }
    data.update(overrides)
    return {"code": 200, "data": data}


def test_valid_response_accepted():
    data = publish._validate_hub_result(_ok_payload(), **EXPECT)
    assert data["plugin_id"] == "plg-123"


def test_business_error_code_rejected():
    """检视复现样例：HTTP 200 + {"code": 403} 不得视为成功。"""
    with pytest.raises(publish.PublishError, match="code != 200"):
        publish._validate_hub_result(
            {"code": 403, "message": "permission_denied"}, **EXPECT
        )


def test_missing_data_rejected():
    with pytest.raises(publish.PublishError, match="data"):
        publish._validate_hub_result({"code": 200}, **EXPECT)


def test_unexpected_asset_type_rejected():
    with pytest.raises(publish.PublishError, match="资产类型"):
        publish._validate_hub_result(_ok_payload(plugin_type="agent-mcp"), **EXPECT)


def test_generic_plugin_type_accepted():
    data = publish._validate_hub_result(
        _ok_payload(plugin_type="plugin"), **EXPECT
    )
    assert data["name"] == "example-plugin"


def test_name_version_mismatch_rejected():
    with pytest.raises(publish.PublishError, match="不一致"):
        publish._validate_hub_result(_ok_payload(version="9.9.9"), **EXPECT)


def test_missing_asset_id_rejected():
    payload = _ok_payload()
    del payload["data"]["plugin_id"]
    with pytest.raises(publish.PublishError, match="asset_id"):
        publish._validate_hub_result(payload, **EXPECT)


def test_conflicting_asset_ids_rejected():
    with pytest.raises(publish.PublishError, match="冲突"):
        publish._validate_hub_result(
            _ok_payload(asset_id="other-id"), **EXPECT
        )


def test_visibility_mismatch_rejected():
    with pytest.raises(publish.PublishError, match="可见性"):
        publish._validate_hub_result(_ok_payload(visibility="private"), **EXPECT)


def test_publish_failed_rejected():
    with pytest.raises(publish.PublishError, match="publish_failed"):
        publish._validate_hub_result(
            _ok_payload(publish_result="publish_failed", visibility=None), **EXPECT
        )


def test_pending_moderation_with_null_visibility_accepted():
    data = publish._validate_hub_result(
        _ok_payload(publish_result="pending_moderation", visibility=None), **EXPECT
    )
    assert data["publish_result"] == "pending_moderation"


def test_null_visibility_without_state_rejected():
    with pytest.raises(publish.PublishError, match="可见性"):
        publish._validate_hub_result(
            _ok_payload(publish_result=None, visibility=None), **EXPECT
        )


def test_non_dict_payload_rejected():
    with pytest.raises(publish.PublishError):
        publish._validate_hub_result("not a dict", **EXPECT)
