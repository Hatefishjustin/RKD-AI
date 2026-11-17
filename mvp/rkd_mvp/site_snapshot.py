"""Canonical site snapshot: ONE fact set, TWO clearly separated digests.

Why this module exists
----------------------
W3 复核发现 ``site_snapshot.sha256`` 实际是"底图文件清单摘要"，而审计里的
``site_snapshot_sha256`` 是另一套算法的完整快照摘要，两者同名不同物，且模型请求
根本没有携带入口与快照哈希。本模块把两件事分开命名并固定算法：

``basemap_files_sha256``
    用户已确认底图五个文件的字节摘要（{文件名: sha256} 的规范化 JSON 的 sha256）。
    它只回答"是否用了同一批底图字节"。

``site_snapshot_sha256``
    完整场地快照（边界、保留区、入口事实与概念假设、未核项、底图文件摘要、
    ``site_verified=false``）的规范化 JSON 摘要。它回答"这次设计用的整份场地
    假设是否同一份"。改入口、改假设理由、改保留区、改未核项都会改变它。

两个摘要都写进：provider 请求正文、受控运行记录、持久候选、适配输出、成果清单。
任何一处不一致都按失败处理，不做"就近重绑"。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

SNAPSHOT_VERSION = "rkd-site-snapshot.v2"
SNAPSHOT_CONTRACT = "rkd-site-basemap.v2"


class SiteSnapshotError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(f"{code}: {message}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def basemap_files_sha256(files: list[dict]) -> str:
    """Digest of the confirmed basemap BYTES only (never the site assumption)."""
    return sha256_hex({str(f["name"]): str(f["sha256"]) for f in files})


def build_snapshot(*, facts: dict, entrance_point_m: list[float] | None,
                   entrance_reason: str, entrance_width_m: float | None = None) -> dict:
    """Build the single snapshot from hash-verified basemap facts + assumption.

    ``entrance_point_m`` is a replaceable concept assumption, never a site fact;
    ``site_verified`` is always false in this batch.
    """
    bw, bh = facts["boundary_mm"]
    payload = {
        "schema_version": SNAPSHOT_VERSION,
        "contract_version": SNAPSHOT_CONTRACT,
        "boundary_source": SNAPSHOT_CONTRACT,
        "width_m": bw / 1000,
        "length_m": bh / 1000,
        "boundary_mm": [bw, bh],
        "keepouts": [{k: v for k, v in item.items()} for item in facts["keepouts"]],
        "entrance_fact": dict(facts["entrance_fact"]),
        "entrance_assumption": {
            "kind": "concept_replaceable",
            "value_m": ([float(entrance_point_m[0]), float(entrance_point_m[1])]
                        if entrance_point_m is not None else None),
            "width_m": (float(entrance_width_m) if entrance_width_m is not None else None),
            "width_known_status": "unknown",
            "reason": str(entrance_reason),
            "site_verified": False,
        },
        "unverified_facts": sorted({str(u) for u in facts["unverified_facts"]}),
        "basemap_files": [{"name": f["name"], "bytes": f["bytes"], "sha256": f["sha256"]}
                          for f in facts["files"]],
        "basemap_files_sha256": basemap_files_sha256(facts["files"]),
        "site_verified": False,
        "note": "事实/概念假设/现场未知分离；入口点为可替换概念假设，不是实测",
    }
    payload["sha256"] = sha256_hex(payload)
    return payload


def recompute_sha256(snapshot: dict) -> str:
    payload = {k: v for k, v in snapshot.items() if k != "sha256"}
    return sha256_hex(payload)


def verify_snapshot_shape(snapshot: dict) -> dict:
    """Recompute the digest and refuse self-inconsistent snapshots."""
    if not isinstance(snapshot, dict):
        raise SiteSnapshotError("SNAPSHOT_NOT_OBJECT", "场地快照不是 JSON 对象")
    if str(snapshot.get("schema_version") or "") != SNAPSHOT_VERSION:
        raise SiteSnapshotError("SNAPSHOT_VERSION_UNSUPPORTED",
                                f"快照版本 {snapshot.get('schema_version')!r} 不是 {SNAPSHOT_VERSION}")
    declared = str(snapshot.get("sha256") or "")
    actual = recompute_sha256(snapshot)
    if not declared or declared != actual:
        raise SiteSnapshotError("SNAPSHOT_SHA_MISMATCH",
                                f"快照自述 sha256={declared[:12]} 与实际 {actual[:12]} 不符")
    files = snapshot.get("basemap_files") or []
    if not files or str(snapshot.get("basemap_files_sha256") or "") != basemap_files_sha256(files):
        raise SiteSnapshotError("BASEMAP_DIGEST_MISMATCH", "底图文件摘要与文件清单不符")
    if snapshot.get("site_verified") is not False:
        raise SiteSnapshotError("SNAPSHOT_OVERCLAIMS_SITE",
                                "本批场地未现场核验，site_verified 必须为 false")
    if str((snapshot.get("entrance_assumption") or {}).get("kind") or "") != "concept_replaceable":
        raise SiteSnapshotError("ENTRANCE_ASSUMPTION_NOT_DECLARED", "入口必须声明 concept_replaceable 假设")
    return {"site_snapshot_sha256": declared,
            "basemap_files_sha256": snapshot["basemap_files_sha256"],
            "boundary_mm": list(snapshot["boundary_mm"]),
            "entrance_point_m": (snapshot["entrance_assumption"].get("value_m")),
            "keepouts": len(snapshot.get("keepouts") or []),
            "unverified_count": len(snapshot.get("unverified_facts") or [])}


def baseline_facts() -> dict:
    """Load facts from the user-confirmed v2 basemap (single source of truth)."""
    from pathlib import Path

    from .realmodel_spatial_adapter import _load_basemap_facts  # lazy: avoid import cycle

    root = Path(__file__).resolve().parents[2]
    return _load_basemap_facts(root / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap")


def provider_site(snapshot: dict) -> dict:
    """The same snapshot expressed for the model request (legacy keys + full snapshot)."""
    verify_snapshot_shape(snapshot)
    assump = snapshot["entrance_assumption"]
    point = assump.get("value_m")
    keepouts = [{"object_id": k["object_id"], "name": k["name"], "rect_m": list(k["rect_m"]),
                 "status": k["status"], "site_verified": False}
                for k in snapshot["keepouts"]]
    obstacles = [{"object_id": k["object_id"], "name": k["name"],
                  "shape": {"type": "rect", "x": str(k["rect_m"][0]), "y": str(k["rect_m"][1]),
                            "width": str(k["rect_m"][2]), "length": str(k["rect_m"][3])},
                  "properties": {"source": SNAPSHOT_CONTRACT, "site_verified": False}}
                 for k in keepouts]
    return {
        "width": snapshot["width_m"], "length": snapshot["length_m"], "unit": "m",
        "boundary_source": SNAPSHOT_CONTRACT,
        "site_snapshot_sha256": snapshot["sha256"],
        "basemap_files_sha256": snapshot["basemap_files_sha256"],
        "site_snapshot": snapshot,
        "obstacles": obstacles,
        "entrance": {"side": snapshot["entrance_fact"]["side"], "point": point,
                     "width": (str(assump["width_m"]) if assump.get("width_m") is not None else None),
                     "source": "concept_assumption", "site_verified": False,
                     "assumption": assump,
                     "basemap_inferred_point_m": snapshot["entrance_fact"].get("inferred_point_m")},
    }


def adapter_site(snapshot: dict) -> dict:
    """The same snapshot expressed for the adapter/geometry gate."""
    verify_snapshot_shape(snapshot)
    assump = snapshot["entrance_assumption"]
    return {
        "contract_version": SNAPSHOT_CONTRACT,
        "boundary_source": SNAPSHOT_CONTRACT,
        "width_m": snapshot["width_m"], "length_m": snapshot["length_m"],
        "site_snapshot": snapshot,
        "snapshot_sha256": snapshot["sha256"],
        "basemap_files_sha256": snapshot["basemap_files_sha256"],
        "keepouts": [{"object_id": k["object_id"], "name": k["name"], "rect_m": list(k["rect_m"]),
                      "status": k["status"], "site_verified": False}
                     for k in snapshot["keepouts"]],
        "entrance": {"side": snapshot["entrance_fact"]["side"], "point_m": assump.get("value_m"),
                     "width_m": assump.get("width_m"), "status": snapshot["entrance_fact"]["status"],
                     "assumption": assump},
        "unverified_facts": list(snapshot["unverified_facts"]),
    }


def snapshot_from_site(site: dict, facts: dict) -> dict:
    """Rebuild the snapshot implied by a caller site and compare hashes.

    Used by the adapter so that the digest cannot be asserted independently of
    the data: the caller's entrance assumption is fed back into the canonical
    builder, and the rebuilt digest must equal the declared one.
    """
    declared = site.get("site_snapshot")
    if isinstance(declared, dict):
        verify_snapshot_shape(declared)
        entrance = (declared.get("entrance_assumption") or {}).get("value_m")
        reason = (declared.get("entrance_assumption") or {}).get("reason") or ""
    else:
        declared = None
        entrance = (site.get("entrance") or {}).get("point_m")
        reason = ((site.get("entrance") or {}).get("assumption") or {}).get("reason") or ""
    rebuilt = build_snapshot(
        facts=facts, entrance_point_m=entrance, entrance_reason=reason,
        entrance_width_m=((site.get("entrance") or {}).get("width_m")
                          if isinstance(site.get("entrance"), dict) else None))
    for key in ("site_snapshot_sha256", "snapshot_sha256", "sha256"):
        value = str(site.get(key) or "")
        if value and value != rebuilt["sha256"]:
            raise SiteSnapshotError(
                "SNAPSHOT_SHA_MISMATCH",
                f"site.{key}={value[:12]} 与按场地数据重算的 {rebuilt['sha256'][:12]} 不符；"
                "入口/保留区/未核项与快照不一致不得放行")
    if declared is not None and declared["sha256"] != rebuilt["sha256"]:
        raise SiteSnapshotError("SNAPSHOT_DATA_MISMATCH",
                                "site.site_snapshot 的摘要与其中的入口/保留区数据重算结果不符")
    return rebuilt
