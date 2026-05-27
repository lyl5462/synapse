"""节点级人机交互机器台账：``archive/<stage>/<node_id>/hitl_context.json``。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from synapse.rd_meeting.hitl_confirmed import resolve_stage_name_for_node
from synapse.rd_meeting.paths import archive_node_dir

logger = logging.getLogger(__name__)

HITL_CONTEXT_FILENAME = "hitl_context.json"


def hitl_context_path(scope_id: str, stage_name: str, node_id: str) -> Path:
    return archive_node_dir(scope_id, stage_name, node_id) / HITL_CONTEXT_FILENAME


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _empty_document(scope_id: str, node_id: str, stage_name: str) -> dict[str, Any]:
    return {
        "scope_id": scope_id,
        "node_id": node_id,
        "stage_name": stage_name,
        "updated_at": _now_iso(),
        "rounds": [],
        "confirmed_by_id": {},
    }


def _load_document(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("read hitl_context failed %s: %s", path, exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def _merge_confirmed_by_id(doc: dict[str, Any], round_record: dict[str, Any]) -> None:
    confirmed = doc.setdefault("confirmed_by_id", {})
    if not isinstance(confirmed, dict):
        confirmed = {}
        doc["confirmed_by_id"] = confirmed
    for q in round_record.get("questions") or []:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or "").strip()
        if qid:
            confirmed[qid] = dict(q)


def append_hitl_context_round(
    scope_id: str,
    node_id: str,
    round_record: dict[str, Any],
    *,
    stage_name: str = "",
    binding: dict[str, Any] | None = None,
) -> Path | None:
    """将一轮 **interactive** 问卷结构化结果追加到 ``hitl_context.json``。"""
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if not sid or not nid or nid == "pending" or not isinstance(round_record, dict):
        return None

    kind = str(round_record.get("intervention_kind") or "interactive").strip().lower()
    if kind != "interactive":
        return None

    stg = (stage_name or "").strip() or resolve_stage_name_for_node(nid, binding)
    if not stg:
        logger.debug("append_hitl_context_round: missing stage_name scope=%s node=%s", sid, nid)
        return None

    path = hitl_context_path(sid, stg, nid)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.is_file():
        doc = _load_document(path)
        if not doc:
            doc = _empty_document(sid, nid, stg)
    else:
        doc = _empty_document(sid, nid, stg)

    rounds = doc.get("rounds")
    if not isinstance(rounds, list):
        rounds = []
        doc["rounds"] = rounds

    rec = dict(round_record)
    rec.setdefault("round", len(rounds) + 1)
    rec.setdefault("submitted_at", _now_iso())
    rounds.append(rec)
    _merge_confirmed_by_id(doc, rec)

    doc["scope_id"] = sid
    doc["node_id"] = nid
    doc["stage_name"] = stg
    doc["updated_at"] = _now_iso()

    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_hitl_context(
    scope_id: str,
    node_id: str,
    *,
    stage_name: str = "",
    binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """读取 ``hitl_context.json``（无文件则空 dict）。"""
    sid = (scope_id or "").strip()
    nid = (node_id or "").strip()
    if not sid or not nid or nid == "pending":
        return {}

    stg = (stage_name or "").strip() or resolve_stage_name_for_node(nid, binding)
    if not stg:
        return {}

    path = hitl_context_path(sid, stg, nid)
    if not path.is_file():
        return {}
    return _load_document(path)
