"""Reproduce the six W3-remediation-architect negatives for a given adapter.

Loads an adapter by file path (frozen baseline or current) and records observed
behaviour for: P1 site snapshot split, P1 self-certified source/parent forgery,
P1 persisted-candidate design loss, P2 contract conflict, P2 net-width legend,
P2 incomplete no-render package.  0 external calls.

  python scripts/repro_w3_control_trust_negatives.py \
      --adapter <path> --label before|after --out <dir> [--sample <model.json>]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "mvp", ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
BASEMAP_DIR = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"
DEFAULT_SAMPLE = ROOT / "deliverables-for-review/roadmap/W3-adapter-remediation/outputs/model.json"


def canon(v) -> bytes:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(v) -> str:
    return hashlib.sha256(canon(v)).hexdigest()


def load_adapter(path: Path):
    spec = importlib.util.spec_from_file_location("repro_adapter_v3", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["repro_adapter_v3"] = mod
    spec.loader.exec_module(mod)
    return mod


def rect_overlap_m2(a: list[float], b: list[float]) -> float:
    """axis-aligned rect [x,y,w,l] overlap in m2 (analytic, not adapter code)."""
    ax, ay, aw, al = a
    bx, by, bw, bl = b
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + al, by + bl) - max(ay, by)
    return max(0.0, w) * max(0.0, h)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample", default=str(DEFAULT_SAMPLE))
    ap.add_argument("--plan", default="")
    ap.add_argument("--no-render-dir", default="")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    A = load_adapter(Path(args.adapter).resolve())
    sample = json.loads(Path(args.sample).read_text(encoding="utf-8"))
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    cases: dict[str, dict] = {}

    # ---- P1-1: the persisted sample has entrance/keepout split --------------
    ent = sample["boundary"]["entrance"]
    stair = next(o for o in sample["boundary"]["obstacles"] if o["object_id"] == "keepout-stair")
    srect = [float(stair["shape"]["x"]), float(stair["shape"]["y"]),
             float(stair["shape"]["width"]), float(stair["shape"]["length"])]
    overlaps = []
    for seg in sample["circulation"]["segments"]:
        sh = seg["shape"]
        r = [float(sh["x"]), float(sh["y"]), float(sh["width"]), float(sh["length"])]
        o = rect_overlap_m2(r, srect)
        if o > 0:
            overlaps.append({"segment_id": seg["segment_id"], "overlap_m2": round(o, 4)})
    path_endpoints = []
    for seg in sample["circulation"]["segments"]:
        sh = seg["shape"]
        if float(sh["x"]) == 0.0:
            path_endpoints.append(float(sh["y"]))
    distance = min((abs(float(ent["point"][1]) - y) for y in path_endpoints), default=None)
    cases["P1_site_split"] = {
        "describe": "持久候选：边界/障碍来自 provider 测试边界，入口标注来自底图假设，二者未贯通",
        "entrance_label_m": [float(ent["point"][0]), float(ent["point"][1])],
        "path_left_end_y_m": path_endpoints,
        "entrance_to_path_distance_m": distance,
        "keepout_overlaps": overlaps,
        "conflict_present": bool(overlaps) or (distance is not None and distance > 0.01),
    }

    # ---- P1-2: self-certified fake run record and fake parent ---------------
    # Use a STRUCTURALLY VALID candidate so the source check is what is tested,
    # not an unrelated geometry guard.
    fake_candidate, _ = A.candidate_from_persisted(sample)
    fake_candidate = copy.deepcopy(fake_candidate)
    # drop the deliberately degenerate near-square legacy segment (zero bbox
    # width) so the source/parent check is the first failing gate.
    fake_candidate["paths"] = [p for p in fake_candidate["paths"]
                               if float(p.get("width") or 0) > 0 and float(p.get("length") or 0) > 0]
    fake_candidate["connections"] = [[a, b] for a, b in fake_candidate["connections"]
                                     if a in {p["segment_id"] for p in fake_candidate["paths"]}
                                     and b in {p["segment_id"] for p in fake_candidate["paths"]}]
    fake_record = {"kind": "real_model_run", "simulated": False,
                   "candidate_sha256": sha(fake_candidate),
                   "input_hash": sha({"anything": True}), "output_sha256": sha({"fake": True}),
                   "model": "invented-model", "prompt_version": "invented-prompt",
                   "project_id": "ningbo-xiecheng", "generated_at": stamp,
                   "record_sha256": ""}
    fake_record["record_sha256"] = sha(fake_record)
    rp = out / "forged-run-record.json"
    rp.write_text(canon(fake_record).decode("utf-8"), encoding="utf-8")
    fake_parent = {"candidate_sha256": sha({"parent": "invented"})}
    pp = out / "forged-parent.json"
    pp.write_text(canon(fake_parent).decode("utf-8"), encoding="utf-8")
    site = {"contract_version": "rkd-site-basemap.v2", "boundary_source": "rkd-site-basemap.v2",
            "width_m": 26.17, "length_m": 17.92,
            "keepouts": [
                {"object_id": "keepout-stair", "name": "楼梯（保留）", "rect_m": [0, 0, 2.4, 8.0], "status": "解析确认"},
                {"object_id": "keepout-bath", "name": "卫生间湿区（保留）", "rect_m": [22.0, 2.6, 4.17, 4.7], "status": "解析确认（仅范围）"}],
            "entrance": {"side": "left", "point_m": [0, 10.3],
                         "assumption": {"kind": "concept_replaceable", "reason": "concept"}},
            "unverified_facts": ["窗（北墙）", "窗（东墙）", "门", "主入口位置", "窗台高 / 窗洞高",
                                 "卫生间内部隔断", "133 项拓扑复核"]}
    prov = {"sha256": sha(fake_candidate), "model_site_boundary_m": [26.17, 17.92],
            "project_id": "ningbo-xiecheng",
            "design_origin": {"kind": "real_model", "declared_by": "forger",
                              "declaration": "self-certified", "run_refs": [str(rp.relative_to(ROOT))]},
            "parent_revision_id": "invented-parent-uid",
            "parent_evidence": {"candidate_sha256": fake_parent["candidate_sha256"],
                                "record_ref": str(pp.relative_to(ROOT))}}
    try:
        m = A.adapt_candidate(fake_candidate, site=site, basemap_dir=BASEMAP_DIR,
                              provenance=prov, created_at=stamp)
        cases["P1_forged_source_parent"] = {"accepted": True,
            "design_origin": m["spatial"]["source"]["design_origin"]["kind"],
            "generation_real_model": m["generation"]["real_model"],
            "parent": m["parent_revision_id"],
            "parent_link_status": m["spatial"]["source"]["parent_link_status"]}
    except Exception as error:  # noqa: BLE001
        cases["P1_forged_source_parent"] = {"accepted": False,
            "error_code": getattr(error, "code", type(error).__name__), "message": str(error)[:200]}

    # ---- P1-3: persisted candidate design loss ------------------------------
    crafted = copy.deepcopy(sample)
    crafted["relationships"] = [{"relation_id": "rel-r", "type": "adjacent",
                                 "source": "zone:foyer", "target": "zone:display",
                                 "statement": "关系不能被丢弃", "source_refs": ["src-r"]}]
    crafted["objects"][0]["material_id"] = "mat-specific"
    crafted["objects"][0]["properties"] = {**crafted["objects"][0].get("properties", {}),
                                           "material_id": "mat-specific"}
    crafted["objects"].append({"object_id": "wall:unknown-kind", "kind": "furniture_cluster",
                               "name": "未知种类", "shape": {"type": "rect", "x": "1", "y": "1",
                               "width": "1", "length": "1"}, "source_refs": ["src-u"], "locked": False,
                               "properties": {"note": "未知对象种类"}})
    try:
        cand, note = A.candidate_from_persisted(crafted)
        cases["P1_persisted_loss"] = {
            "relationships_mapped": len(cand.get("relationships") or []),
            "material_bindings": [o.get("material_id") for o in (cand.get("zones") or [])],
            "focal_mapped": bool(cand.get("focal_point")),
            "unknown_kinds_reported": bool(note.get("unsupported_kinds") or note.get("unknown_kinds")),
            "note_keys": sorted(note.keys()),
        }
    except Exception as error:  # noqa: BLE001
        cases["P1_persisted_loss"] = {"error": type(error).__name__, "message": str(error)[:200]}

    # ---- P2-4: contract conflict (same top version, two validators) ---------
    legacy = json.loads((ROOT / "contracts/v1/ai-design-option.schema.json").read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator
    errs = [e.message for e in Draft202012Validator(legacy).iter_errors(sample)]
    cases["P2_contract_conflict"] = {
        "document_schema_version": sample["schema_version"],
        "legacy_schema_expected": legacy["properties"]["schema_version"].get("const"),
        "legacy_error_count": len(errs),
        "has_top_level_version_bump": sample["schema_version"] != legacy["properties"]["schema_version"].get("const"),
    }

    # ---- P2-5: net-width legend and ambiguous axis --------------------------
    svg = Path(args.plan) if args.plan else (ROOT / "deliverables-for-review/roadmap/W3-adapter-remediation/outputs/plan.svg")
    svg_text = svg.read_text(encoding="utf-8") if svg.is_file() else ""
    ambient = next((c for c in sample["spatial"]["circulation"] if c.get("axis") == "ambiguous_unknown"), None)
    cases["P2_netwidth_legend"] = {
        "legend_claims_net_width": "净宽" in svg_text,
        "legend_fragments": re.findall(r"主动线[^<]{0,40}", svg_text)[:3],
        "ambiguous_axis": ambient.get("axis") if ambient else None,
        "ambiguous_path_mm": ambient.get("path_mm") if ambient else None,
        "ambiguous_zero_length": bool(ambient and len(ambient["path_mm"]) == 2 and
                                      ambient["path_mm"][0] == ambient["path_mm"][1]),
    }

    # ---- P2-6: incomplete no-render package ---------------------------------
    # Baseline --no-render still writes a package without render; inspect the
    # architect's independent no-render run.
    nr = Path(args.no_render_dir) if args.no_render_dir else (ROOT / "var/evidence/roadmap/W3-remediation-architect/out/outputs")
    names = sorted(p.name for p in nr.iterdir()) if nr.is_dir() else []
    cases["P2_no_render_package"] = {
        "has_manifest": "manifest.json" in names,
        "has_package_zip": "package.zip" in names,
        "has_render": "render.png" in names,
        "manifest_declares_incomplete": False,
    }
    if "manifest.json" in names:
        man = json.loads((nr / "manifest.json").read_text(encoding="utf-8"))
        blob = canon(man).decode("utf-8")
        cases["P2_no_render_package"]["manifest_declares_incomplete"] = any(
            word in blob for word in ("incomplete", "not_run", "不完整", "未渲染"))

    evidence = {"schema_version": "rkd-w3-control-trust-repro.v1", "label": args.label,
                "adapter": str(Path(args.adapter).resolve()),
                "adapter_sha256": hashlib.sha256(Path(args.adapter).read_bytes()).hexdigest(),
                "sample": str(Path(args.sample).resolve()),
                "sample_sha256": hashlib.sha256(Path(args.sample).read_bytes()).hexdigest(),
                "executed_at": stamp, "cases": cases,
                "external_calls": 0, "cost_cny": 0, "keys_used": False}
    (out / "repro.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    print(f"{args.label}: {len(cases)} cases -> {out / 'repro.json'}")
    for k, v in cases.items():
        print(" ", k, json.dumps(v, ensure_ascii=False)[:220])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
