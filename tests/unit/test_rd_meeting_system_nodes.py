"""系统节点：sandbox_build / auto_split / env_pregen / human_confirm 约束。"""

from __future__ import annotations

from pathlib import Path

from synapse.rd_meeting.auto_split_assets import bootstrap_auto_split, format_auto_split_report
from synapse.rd_meeting.binding import resolve_node_binding
from synapse.rd_meeting.env_pregen_assets import _copy_tree_files, bootstrap_env_pregen
from synapse.rd_meeting.sandbox_assets import materialize_repo_to_sandbox
from synapse.rd_sop.manifest import default_human_confirm, is_system_node


def test_sandbox_build_is_system_type():
    assert is_system_node("sandbox_build")
    assert default_human_confirm("sandbox_build") is False


def test_auto_split_and_env_pregen_are_system_type():
    assert is_system_node("auto_split")
    assert is_system_node("env_pregen")
    assert default_human_confirm("auto_split") is False
    assert default_human_confirm("env_pregen") is False


def test_system_node_binding_forbids_human_confirm(monkeypatch):
    monkeypatch.setattr(
        "synapse.rd_meeting.binding.load_meeting_room_config",
        lambda: {
            "node_overrides": {
                "sandbox_build": {"human_confirm": True},
                "auto_split": {"human_confirm": True},
            }
        },
    )
    for nid in ("sandbox_build", "auto_split", "env_pregen"):
        b = resolve_node_binding(nid)
        assert b["type"] == "system"
        assert b["human_confirm"] is False
        assert b["hitl_form_schema"] is None


def test_materialize_repo_to_sandbox_skips_utf8(monkeypatch, tmp_path):
    scope_id = "sb-scope"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    dest = tmp_path / "work" / scope_id / "sandbox" / "demo"
    dest.mkdir(parents=True)
    (dest / ".git").mkdir()
    legacy = dest / "legacy.txt"
    legacy.write_bytes("编码测试".encode("gbk"))

    monkeypatch.setattr(
        "synapse.rd_meeting.sandbox_assets._run_git",
        lambda *args, **kwargs: (True, ""),
    )

    entry = materialize_repo_to_sandbox(
        scope_id,
        {"repo_name": "demo", "repo_url": "https://example.com/demo.git", "repo_branch": "main"},
    )
    assert entry["status"] == "ok"
    assert legacy.read_bytes() == "编码测试".encode("gbk")


def test_auto_split_from_userwork(monkeypatch, tmp_path):
    scope_id = "D12345"
    monkeypatch.setattr(
        "synapse.rd_meeting.auto_split_assets._load_userwork_list",
        lambda: [
            {
                "demand_no": scope_id,
                "owned_work_items": [
                    {"task_no": "T001", "task_title": "子单A", "sop_node": "pending"},
                ],
            }
        ],
    )
    monkeypatch.setattr(
        "synapse.rd_meeting.auto_split_assets._fetch_portal_task_nos",
        lambda _dn: (["T001", "T002"], ""),
    )

    assets = bootstrap_auto_split("demand", scope_id)
    assert assets["status"] == "ok"
    assert len(assets["local_tasks"]) == 1
    assert "T002" in assets["portal_task_nos"]
    report = format_auto_split_report(assets, node_name="自动拆单")
    assert "研发子单拆分清单" in report
    assert "T001" in report


def test_env_pregen_copies_entropy(monkeypatch, tmp_path):
    scope_id = "env-scope"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    from synapse.rd_meeting.paths import archive_node_dir, env_entropy_dir
    from synapse.rd_sop.nodes import stage_name_for_id

    stage = stage_name_for_id(2)
    src = archive_node_dir(scope_id, stage, "entropy_gen")
    src.mkdir(parents=True)
    (src / "agent.md").write_text("# agent", encoding="utf-8")
    (src / "rule.md").write_text("# rule", encoding="utf-8")

    copied = _copy_tree_files(src, env_entropy_dir(scope_id))
    assert len(copied) == 2
    assert (env_entropy_dir(scope_id) / "agent.md").read_text(encoding="utf-8") == "# agent"


def test_bootstrap_env_pregen_partial_without_catalog(monkeypatch, tmp_path):
    scope_id = "env2"
    monkeypatch.setattr("synapse.rd_meeting.paths.work_root", lambda: tmp_path / "work")
    from synapse.rd_meeting.paths import archive_node_dir, product_doc_root
    from synapse.rd_sop.nodes import stage_name_for_id

    stage = stage_name_for_id(2)
    src = archive_node_dir(scope_id, stage, "entropy_gen")
    src.mkdir(parents=True)
    (src / "agent.md").write_text("x", encoding="utf-8")

    doc_root = product_doc_root(scope_id)
    (doc_root / "产品架构").mkdir(parents=True)
    (doc_root / "产品架构" / "arch.md").write_text("doc", encoding="utf-8")

    monkeypatch.setattr(
        "synapse.rd_meeting.env_pregen_assets._materialize_doc_to_env",
        lambda *a, **k: {"doc_type": "x", "status": "skipped", "error": "skip"},
    )

    assets = bootstrap_env_pregen(scope_id, "prod-x", wire_row={"prod": "prod-x", "repos": [], "docs": []})
    assert assets["status"] in ("ok", "partial")
    assert assets["entropy"].get("status") == "ok"
    assert assets["product_doc_mirror"].get("status") == "ok"
