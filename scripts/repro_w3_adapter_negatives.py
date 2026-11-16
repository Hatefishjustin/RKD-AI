"""Reproduce the architect's R01-R06 negatives against a given adapter module.

The adapter is loaded by file path so the SAME cases run against the frozen
dcc11f7 baseline (before) and the remediated module (after):

  python scripts/repro_w3_adapter_negatives.py \
      --adapter <path-to-realmodel_spatial_adapter.py> --label before --out <dir>

0 external calls. Records per-case observed behaviour; does not grade pass/fail
policy (the verifier does that).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Common fixtures, independent of any adapter version.
BASEMAP_DIR = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"
SITE = {
    "contract_version": "rkd-site-basemap.v2",
    "boundary_source": "rkd-site-basemap.v2",
    "width_m": 26.17, "length_m": 17.92,
    "unverified_facts": [
        "窗（北墙）", "窗（东墙）", "门", "主入口位置", "窗台高 / 窗洞高",
        "卫生间内部隔断", "133 项拓扑复核",
    ],
    "entrance": {"side": "left", "point_m": [0, 10.3], "width_m": 1.8, "status": "待现场复核",
                 "assumption": {"kind": "concept_replaceable",
                                "reason": "底图仅推断西门厅，点位为 W2 概念样板的暂用假设，可现场复核后替换"}},
    "keepouts": [
        {"object_id": "keepout-stair", "name": "楼梯保留区", "rect_m": [0, 0, 2.4, 8.0], "status": "解析确认"},
        {"object_id": "keepout-bath", "name": "卫生间湿区", "rect_m": [22.0, 2.6, 4.17, 4.7], "status": "解析确认（仅范围）"},
    ],
}
CANDIDATE = {
    "strategy_id": "repro-fixture", "concept": "复现夹具", "statement": "复现夹具，非设计",
    "zones": [
        {"object_id": "zone:a", "name": "A", "x": 3.0, "y": 9.0, "width": 5.0, "length": 6.5,
         "zone_role": "foyer", "sequence_role": "opening", "intent": "x"},
        {"object_id": "zone:b", "name": "B", "x": 8.2, "y": 7.0, "width": 7.0, "length": 7.5,
         "zone_role": "primary_display", "sequence_role": "climax", "intent": "x"},
        {"object_id": "zone:c", "name": "C", "x": 16.0, "y": 9.0, "width": 5.5, "length": 6.0,
         "zone_role": "deep_talk", "sequence_role": "closing", "intent": "x"},
    ],
    "walls": [{"object_id": "wall:f", "name": "片墙", "x": 7.6, "y": 10.5,
               "width": 0.14, "length": 3.0, "wall_type": "feature"}],
    "furniture": [{"object_id": "f:d", "name": "前台", "x": 3.6, "y": 11.0,
                   "width": 1.4, "length": 0.6, "furniture_type": "reception_desk",
                   "parent_object_id": "zone:a"}],
    "focal_point": {"object_id": "focal:hero", "name": "中岛", "x": 10.5, "y": 9.5,
                    "width": 1.8, "length": 1.2, "furniture_type": "island", "statement": "焦点"},
    "paths": [
        {"segment_id": "path-south", "x": 0, "y": 6.0, "width": 22.0, "length": 1.4},
        {"segment_id": "path-west", "x": 2.2, "y": 7.4, "width": 1.4, "length": 7.6},
    ],
    "connections": [["path-south", "path-west"]],
    "circulation_kind": "branch",
    "materials": [{"material_id": "mat-warm", "name": "暖木", "intent": "未选产品"}],
    "cost_unknown": ["价源"],
}
PROV = {
    "artifact_id": "repro-fixture", "sha256": hashlib.sha256(b"repro-v1").hexdigest(),
    "set_id": "repro", "option_id": "repro", "revision_no": 1, "parent_revision_id": None,
    "actor_id": "repro", "model_site_boundary_m": [26.17, 17.92],
    "design_origin": {"kind": "fixture", "declared_by": "repro", "declaration": "离线夹具", "run_refs": []},
}


def load_adapter(path: Path):
    spec = importlib.util.spec_from_file_location("repro_adapter", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["repro_adapter"] = mod
    spec.loader.exec_module(mod)
    return mod


def observe(fn):
    try:
        return {"raised": False, "value": fn()}
    except Exception as error:  # noqa: BLE001
        return {"raised": True, "error_code": getattr(error, "code", None),
                "error_type": type(error).__name__, "message": str(error)[:300]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    A = load_adapter(Path(args.adapter).resolve())
    cases: dict[str, dict] = {}
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    def prov_for(cand):
        """Bind provenance.sha256 to the ACTUAL candidate bytes (R02 v2 rule)."""
        p = copy.deepcopy(PROV)
        p["sha256"] = hashlib.sha256(json.dumps(cand, ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":")).encode("utf-8")).hexdigest()
        return p

    def adapt(site=None, cand=None, prov=None):
        c = cand or CANDIDATE
        return A.adapt_candidate(c, site=site or SITE, basemap_dir=BASEMAP_DIR,
                                 provenance=prov if prov is not None else prov_for(c),
                                 created_at=stamp)

    # R01a: keepouts emptied by caller -- does the adapter still claim v2 and succeed?
    empty_keepouts = dict(SITE, keepouts=[])
    r = observe(lambda: adapt(site=empty_keepouts))
    cases["R01a_empty_keepouts"] = {
        "describe": "调用者把 keepouts 改为 [] 仍声称 v2",
        "observed": r,
        "accepted": not r["raised"],
        "keepouts_in_output": (len(r["value"]["boundary"]["obstacles"])
                               if not r["raised"] else None),
    }
    # R01b: entrance point changed to [0,1]
    changed_ent = dict(SITE, entrance={"side": "left", "point_m": [0, 1], "width_m": 1.8})
    r = observe(lambda: adapt(site=changed_ent))
    cases["R01b_changed_entrance"] = {
        "describe": "调用者把入口点改为 [0,1]",
        "observed": r, "accepted": not r["raised"],
        "entrance_in_output": (r["value"]["boundary"]["entrance"]["point"]
                               if not r["raised"] else None),
    }
    # R02a: fabricated run_refs + real_model claim; check generation consistency
    fake_prov = prov_for(CANDIDATE)
    fake_prov["design_origin"] = {"kind": "real_model", "declared_by": "self",
                                  "declaration": "伪造", "run_refs": ["invented"]}
    r = observe(lambda: adapt(prov=fake_prov))
    if not r["raised"]:
        cases["R02a_fake_run_refs"] = {
            "describe": "自报 run_refs=['invented'] 声明 real_model",
            "observed": r, "accepted": True,
            "design_origin": r["value"]["spatial"]["source"]["design_origin"]["kind"],
            "generation_real_model": r["value"]["generation"]["real_model"],
            "contradiction": (r["value"]["spatial"]["source"]["design_origin"]["kind"] == "real_model"
                              and r["value"]["generation"]["real_model"] is False),
        }
    else:
        cases["R02a_fake_run_refs"] = {"describe": "自报 run_refs=['invented'] 声明 real_model",
                                       "observed": r, "accepted": False, "contradiction": False}
    # R02b: wrong caller-declared sha256 in provenance
    bad_sha = prov_for(CANDIDATE)
    bad_sha["sha256"] = "0" * 64
    r = observe(lambda: adapt(prov=bad_sha))
    cases["R02b_wrong_candidate_sha"] = {
        "describe": "provenance.sha256 全 0 与候选不符", "observed": r, "accepted": not r["raised"],
        "source_sha": (r["value"]["spatial"]["source"]["sha256"] if not r["raised"] else None),
    }
    # R02c: fabricated parent revision
    bad_parent = prov_for(CANDIDATE)
    bad_parent["parent_revision_id"] = "invented-parent-uid"
    r = observe(lambda: adapt(prov=bad_parent))
    cases["R02c_fake_parent"] = {
        "describe": "parent_revision_id 指向不存在父版本", "observed": r, "accepted": not r["raised"],
        "parent_in_output": (r["value"]["parent_revision_id"] if not r["raised"] else None),
        "diff_baseline": (r["value"]["spatial"]["adaptation"].get("diff_baseline")
                          if not r["raised"] else None),
    }
    # R04a: vertical path -> horizontal centreline?
    vert = copy.deepcopy(CANDIDATE)
    vert["paths"][1] = {"segment_id": "path-west", "x": 2.2, "y": 7.4, "width": 1.4, "length": 7.6}
    m = adapt(cand=vert)
    seg = next(c for c in m["spatial"]["circulation"] if c["object_id"] == "path-west")
    cases["R04a_vertical_path"] = {
        "describe": "1.4x7.6m 纵向 path-west 的中心线方向",
        "path_mm": seg["path_mm"],
        "is_horizontal": abs(seg["path_mm"][0][1] - seg["path_mm"][-1][1]) < 1,
        "is_vertical": abs(seg["path_mm"][0][0] - seg["path_mm"][-1][0]) < 1,
    }
    # R04b: branch forced to loop?
    cases["R04b_branch_kind"] = {
        "describe": "circulation_kind=branch 是否被改成 loop",
        "in": CANDIDATE["circulation_kind"],
        "out": m["circulation"]["kind"],
        "forced_loop": m["circulation"]["kind"] == "loop",
    }
    # R06: diff field coverage
    prev = adapt()
    nxt_cand = copy.deepcopy(CANDIDATE)
    nxt_cand["materials"][0]["name"] = "changed-material"
    nxt_cand["walls"][0]["wall_type"] = "curved_intent"
    nxt = prov_for(nxt_cand)
    nxt["revision_no"] = 2
    nxt["parent_revision_id"] = None  # no fabricated parent; v2 requires evidence for one
    nxt_m = A.adapt_candidate(nxt_cand, site=SITE, basemap_dir=BASEMAP_DIR,
                              provenance=nxt, created_at=stamp)
    delta = A.diff_spatial(prev["spatial"], nxt_m["spatial"])
    fields = sorted({d.get("field", "") for d in delta})
    cases["R06_diff_coverage"] = {
        "describe": "diff_spatial 覆盖字段", "fields": fields, "diff_count": len(delta),
        "covers_materials": any("material" in f for f in fields),
        "covers_source": any("source" in f for f in fields),
        "covers_site": any("boundary" in f or "keepout" in f for f in fields),
        "covers_semantic": any("semantic" in f for f in fields),
        "covers_parent": any("parent" in f for f in fields),
    }
    evidence = {
        "schema_version": "rkd-w3-adapter-repro.v1", "label": args.label,
        "adapter_path": str(Path(args.adapter).resolve()),
        "adapter_sha256": hashlib.sha256(Path(args.adapter).read_bytes()).hexdigest(),
        "executed_at": stamp, "basemap_dir": str(BASEMAP_DIR),
        "external_calls": 0, "cost_cny": 0, "key_used": False,
        "cases": cases,
    }
    (out / "repro.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    print(f"{args.label}: wrote {out / 'repro.json'}, {len(cases)} cases")
    for k, v in cases.items():
        print(" ", k, "accepted" if v.get("accepted") else
              ("raised=" + str(v.get("observed", {}).get("error_code")) if "observed" in v else
               json.dumps({kk: vv for kk, vv in v.items() if kk in
                           ("is_horizontal", "is_vertical", "forced_loop", "diff_count")}, ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
