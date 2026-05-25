"""产品定位与 devservice URL（契约对齐 ProductManager.getProdInfo）。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.devservice import (
    format_host_authority,
    read_devservice_host,
    unified_service_base_url,
)
from synapse.rd_meeting.init_context import normalize_node_init_log_data
from synapse.rd_meeting.product_context import (
    match_prod_row_by_prod,
    parse_get_prod_info_response,
    resolve_product_for_meeting,
)


def test_parse_get_prod_info_like_product_manager():
    body = {
        "code": 0,
        "message": "产品查询成功",
        "total": 2,
        "data": [{"prod": "a", "version": "v1"}, {"prod": "b", "version": "v2"}],
    }
    parsed = parse_get_prod_info_response(body)
    assert parsed.ok
    assert len(parsed.data) == 2


def test_match_prod_row_by_prod_only():
    rows = [{"prod": "CBOSS_BSS_ZMDB_V9.0", "version": "99|CBOSS_BSS_ZMDB_V9.0"}]
    assert match_prod_row_by_prod(rows, "CBOSS_BSS_ZMDB_V9.0") is not None
    assert match_prod_row_by_prod(rows, "CBOSS_BSS_ZMDB_V9.0")["prod"] == "CBOSS_BSS_ZMDB_V9.0"
    assert match_prod_row_by_prod(rows, "99|CBOSS_BSS_ZMDB_V9.0") is None


def test_devservice_urls_from_ip_file(tmp_path, monkeypatch):
    ip_file = tmp_path / "devservice.ip"
    ip_file.write_text("192.168.1.10\n", encoding="utf-8")
    monkeypatch.setattr("synapse.rd_meeting.devservice._devservice_ip_path", lambda: ip_file)
    monkeypatch.setattr(
        "synapse.rd_meeting.devservice._devservice_ip_path_legacy",
        lambda: tmp_path / "missing.ip",
    )
    assert unified_service_base_url() == "http://192.168.1.10:10001"


def test_format_host_authority_ipv6():
    assert format_host_authority("2001:db8::1") == "[2001:db8::1]"


def test_resolve_product_by_userwork_prod(monkeypatch, tmp_path):
    scope_id = "prod-ctx-1"
    prod_name = "myprod"
    uw_path = tmp_path / "userwork.json"
    uw_path.write_text(
        json.dumps(
            {
                "list": [
                    {
                        "demand_no": scope_id,
                        "demand_title": "T",
                        "prod": prod_name,
                        "owned_work_items": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    work = tmp_path / "work" / scope_id
    work.mkdir(parents=True)
    pipe_path = work / "meeting_pipeline.json"
    pipe_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope_type": "demand",
                "scope_id": scope_id,
                "flow_step": "node_init",
                "phase": "idle",
                "context": {
                    "prod_catalog": [
                        {
                            "prod": prod_name,
                            "version": "1|VER",
                            "function": "客户管理:CRM模块|订单中心:订单处理",
                            "repo_info": [{"repo_url": "https://git.example.com/foo.git"}],
                            "doc_process": [{"doc_type": "产品架构", "doc_process_state": "D"}],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    for mod in (
        "synapse.api.routes.dev_iwhalecloud",
        "synapse.rd_meeting.userwork_sync",
    ):
        monkeypatch.setattr(f"{mod}._owner_order_file_name", lambda: uw_path)
        monkeypatch.setattr(f"{mod}._owner_order_file_lock_path", lambda: tmp_path / "uw.lock")
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    monkeypatch.setattr(
        "synapse.rd_meeting.product_context.unified_service_base_url",
        lambda: "http://10.0.0.1:10001",
    )
    product, system = resolve_product_for_meeting("demand", scope_id)
    assert "gitnexus_url" not in system
    assert "gnx_cache_base_dir" not in system
    assert product["locator_code"] == "ok"
    assert product["prod"] == prod_name
    assert product["prod_feature"] == "客户管理:CRM模块|订单中心:订单处理"
    assert product["function"] == product["prod_feature"]
    assert product["repos"][0]["repo_name"] == "foo"


def test_normalize_node_init_backfills_prod_feature_from_function():
    data = normalize_node_init_log_data(
        {"product": {"prod": "p1", "function": "模块A:说明A|模块B:说明B"}}
    )
    assert data["product"]["prod_feature"] == "模块A:说明A|模块B:说明B"
