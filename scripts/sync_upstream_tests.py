#!/usr/bin/env python3
"""Sync tests/ from upstream openakita into the Synapse fork.

- Copies missing upstream test modules with Synapse branding.
- Updates shared modules when upstream is newer (by test count heuristic).
- Never overwrites local-only customization tests (rd_meeting, dev_iwhalecloud, …).
- Always refreshes tests/conftest.py from upstream (fixtures drift).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_TESTS = Path("D:/github/openakita/tests")
LOCAL_TESTS = ROOT / "tests"

# Paths only in the fork — never replace from upstream.
LOCAL_ONLY: frozenset[str] = frozenset(
    {
        "integration/test_api_gitnexus.py",
        "integration/test_dev_iwhalecloud_api.py",
        "unit/test_collaboration_work_plan.py",
        "unit/test_dev_iwhalecloud_knowledge_repos.py",
        "unit/test_dev_tool_slug.py",
        "unit/test_git_token.py",
        "unit/test_intervention_panel.py",
        "unit/test_mark_human_gate_schema.py",
        "unit/test_meeting_room_handler.py",
        "unit/test_security.py",
        "unit/test_solution_review.py",
    }
    | {f"unit/test_rd_meeting_{name}.py" for name in (
        "agent_activity",
        "agent_context_probe",
        "agent_prompt",
        "agent_runtime",
        "agent_trace",
        "chat_display",
        "dynamic_prompt",
        "flow_log",
        "historical_reprocess",
        "hitl_confirmed",
        "hitl_context",
        "hitl_feedback",
        "hitl_lifecycle",
        "hitl_questionnaire",
        "hitl_submission",
        "host_prompt",
        "host_prompt_cache",
        "init_context",
        "live_phase_artifacts",
        "live_route",
        "node_history",
        "node_review",
        "participants",
        "phase0",
        "phase1",
        "phase2",
        "phase3",
        "phase4_config",
        "phase4_skill",
        "phase5_node_enable",
        "pipeline",
        "pipeline_chat",
        "pipeline_node_cursor",
        "pipeline_node_finish",
        "pipeline_node_review",
        "prior_outputs",
        "product_assets",
        "product_context",
        "questionnaire_repair",
        "reprocess_prep",
        "room_stop",
        "routes_node_review",
        "skip_before_init",
        "sop_stage_hooks",
        "system_nodes",
        "user_context_intervene",
        "work_plan",
    )}
)

# Always take upstream (infrastructure / global fixtures).
FORCE_UPSTREAM: frozenset[str] = frozenset(
    {
        "conftest.py",
        "fixtures/factories.py",
        "fixtures/mock_llm.py",
    }
)

sys.path.insert(0, str(ROOT / "scripts"))
from brand_synapse_tree import transform_text  # noqa: E402


def _rel(py: Path, base: Path) -> str:
    return py.relative_to(base).as_posix()


def _test_def_count(text: str) -> int:
    return len(re.findall(r"^\s*def test_", text, re.MULTILINE))


def _is_local_only(rel: str) -> bool:
    if rel in LOCAL_ONLY:
        return True
    return rel.startswith("unit/test_rd_meeting_")


def _sync_one(rel: str, up_path: Path) -> str:
    """Return action label: added | updated | kept | skipped."""
    if _is_local_only(rel):
        return "skipped"

    raw = up_path.read_text(encoding="utf-8")
    branded = transform_text(raw, ui_dist=False)
    dest = LOCAL_TESTS / rel

    existed = dest.is_file()

    if rel in FORCE_UPSTREAM:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(branded, encoding="utf-8", newline="\n")
        return "updated" if existed else "added"

    if not existed:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(branded, encoding="utf-8", newline="\n")
        return "added"

    local_text = dest.read_text(encoding="utf-8")
    if branded.strip() == local_text.strip():
        return "unchanged"

    up_tests = _test_def_count(branded)
    loc_tests = _test_def_count(local_text)
    if loc_tests > up_tests:
        return "kept"

    dest.write_text(branded, encoding="utf-8", newline="\n")
    return "updated"


def main() -> None:
    if not UPSTREAM_TESTS.is_dir():
        raise SystemExit(f"Missing upstream tests: {UPSTREAM_TESTS}")

    stats: dict[str, int] = {}
    kept: list[str] = []

    for up_path in sorted(UPSTREAM_TESTS.rglob("*.py")):
        rel = _rel(up_path, UPSTREAM_TESTS)
        action = _sync_one(rel, up_path)
        stats[action] = stats.get(action, 0) + 1
        if action == "kept":
            kept.append(rel)

    print(f"Upstream: {UPSTREAM_TESTS}")
    print(f"Local:    {LOCAL_TESTS}")
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")
    if kept:
        print(f"  kept (local has more tests, {len(kept)}):")
        for p in kept[:30]:
            print(f"    - {p}")
        if len(kept) > 30:
            print(f"    ... +{len(kept) - 30} more")


if __name__ == "__main__":
    main()
