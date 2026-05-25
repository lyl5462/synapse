"""room_opened 产品代码 / 文档落盘。"""

from __future__ import annotations

import json

import pytest

from synapse.rd_meeting.paths import (
    product_code_dir,
    product_doc_dir,
    sanitize_fs_segment,
    sanitize_work_order_segment,
)
from synapse.rd_meeting.convert_to_utf8 import convert_directory_to_utf8
from synapse.rd_meeting.product_assets import (
    _materialize_repo,
    bootstrap_product_assets,
    enrich_product_with_assets,
    fetch_prod_doc,
    save_product_assets_to_pipeline,
)
from synapse.rd_meeting.room_skill import build_product_workspace_paths_section


def test_sanitize_fs_segment_keeps_chinese_doc_type():
    assert sanitize_fs_segment("产品架构") == "产品架构"
    assert sanitize_fs_segment("产品需求") == "产品需求"
    assert sanitize_work_order_segment("产品架构") == "default"


def test_convert_directory_to_utf8_converts_gbk(tmp_path):
    src = tmp_path / "demo.txt"
    src.write_bytes("中文内容".encode("gbk"))
    result = convert_directory_to_utf8(tmp_path)
    assert result["stats"]["converted"] == 1
    assert src.read_text(encoding="utf-8") == "中文内容"


def test_materialize_repo_converts_to_utf8_after_clone(monkeypatch, tmp_path):
    scope_id = "utf8-scope"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    dest = product_code_dir(scope_id, "demo")
    dest.mkdir(parents=True)
    (dest / ".git").mkdir()
    (dest / "legacy.txt").write_bytes("编码测试".encode("gbk"))

    monkeypatch.setattr(
        "synapse.rd_meeting.product_assets._run_git",
        lambda *args, **kwargs: (True, ""),
    )

    entry = _materialize_repo(
        scope_id,
        {"repo_name": "demo", "repo_url": "https://example.com/demo.git", "repo_branch": "main"},
    )
    assert entry["status"] == "ok"
    assert (dest / "legacy.txt").read_text(encoding="utf-8") == "编码测试"


def test_bootstrap_writes_code_and_doc(monkeypatch, tmp_path):
    scope_id = "asset-scope-1"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")

    wire = {
        "prod": "myprod",
        "repo_info": [
            {
                "repo_url": "https://github.com/example/demo.git",
                "repo_branch": "1|main",
            }
        ],
        "doc_process": [
            {"doc_type": "产品架构", "doc_process_state": "D"},
            {"doc_type": "产品需求", "doc_process_state": "I"},
        ],
    }

    monkeypatch.setattr(
        "synapse.rd_meeting.product_assets._materialize_repo",
        lambda sid, repo: {
            "repo_name": "demo",
            "local_path": str(product_code_dir(sid, "demo")),
            "status": "ok",
            "error": "",
        },
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.product_assets._materialize_doc",
        lambda sid, prod, doc: {
            "doc_type": doc["doc_type"],
            "local_path": str(product_doc_dir(sid, str(doc["doc_type"]))),
            "files": ["a.md"],
            "status": "ok" if doc["doc_type"] == "产品架构" else "skipped",
            "error": "",
        },
    )

    assets = bootstrap_product_assets(scope_id, "myprod", wire_row=wire)
    assert assets["status"] in ("ok", "partial")
    assert len(assets["repos"]) == 1
    assert assets["repos"][0]["status"] == "ok"
    assert len(assets["docs"]) == 2

    product = enrich_product_with_assets({"prod": "myprod", "repos": [], "docs": []}, assets)
    assert product["code_root"]
    assert product["doc_root"]
    assert product["repos"][0]["local_path"]

    init_ctx = {
        "product": product,
        "system": {"product_code_root": product["code_root"], "product_doc_root": product["doc_root"]},
    }
    block = build_product_workspace_paths_section(init_ctx)
    assert "产品工作区路径" in block
    assert "code" in block
    assert "doc" in block


def test_fetch_prod_doc_parses_response(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "message": "ok",
                "data": {"doc_content": [{"doc_name": "x.md", "content": "# hi"}]},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None):
            return FakeResp()

    monkeypatch.setattr(
        "synapse.rd_meeting.product_assets.unified_service_base_url",
        lambda: "http://127.0.0.1:10001",
    )
    monkeypatch.setattr("synapse.rd_meeting.product_assets.httpx.Client", FakeClient)

    docs, err = fetch_prod_doc("p", "产品架构")
    assert not err
    assert docs[0]["doc_name"] == "x.md"
    assert docs[0]["content"] == "# hi"


def test_save_product_assets_to_pipeline(monkeypatch, tmp_path):
    scope_id = "asset-pipe-1"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    work = tmp_path / "work" / scope_id
    work.mkdir(parents=True)
    from synapse.rd_meeting.paths import meeting_pipeline_path

    meeting_pipeline_path(scope_id).write_text(
        json.dumps({"schema_version": 1, "context": {}}),
        encoding="utf-8",
    )
    save_product_assets_to_pipeline(scope_id, {"prod": "p", "status": "ok"})
    raw = json.loads(meeting_pipeline_path(scope_id).read_text(encoding="utf-8"))
    assert raw["context"]["product_assets"]["prod"] == "p"
