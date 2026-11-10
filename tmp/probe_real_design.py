"""One-off probe: can the real model produce two geometry-valid designs?"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))

from rkd_mvp.ai_design_geometry import candidates_are_structurally_different, validate_model  # noqa: E402
from rkd_mvp.ai_design_option_provider import RealModelDesignOptionProvider, load_design_option_config  # noqa: E402

key = os.environ["RKD_TEST_KEY"]
env = {
    "RKD_AI_DESIGN_PROVIDER": "openai-compatible", "RKD_AI_PROVIDER": "openai-compatible",
    "RKD_AI_BASE_URL": "https://api.codelink.chat/v1", "RKD_AI_MODEL": "gpt-5.6-sol",
    "RKD_AI_API_KEY": key, "RKD_AI_EXTERNAL_CONTEXT": "false",
    "RKD_AI_DESIGN_MAX_ATTEMPTS": "3", "RKD_AI_TIMEOUT_SECONDS": "180",
    "RKD_AI_DESIGN_MAX_OUTPUT_TOKENS": "6000",
}
config = load_design_option_config(env)
provider = RealModelDesignOptionProvider(config, key, environ=env,
                                         run_log_dir=ROOT / "var" / "ai-model-runs" / "probe")
brief = {
    "requirements": [{"statement": "开放交流与展示，入口在左侧，暖木色，保留独立洽谈",
                       "priority": "high", "known_status": "known"}],
    "design_intent": [{"statement": "更开放的展示与交流关系，同时保留安静的独立洽谈",
                        "priority": "high", "known_status": "inferred"},
                       {"statement": "材料氛围倾向暖木色，具体规格与样板未确定",
                        "priority": "normal", "known_status": "inferred"}],
    "conflicts": [{"conflict_id": "c-open-private", "statement": "开放交流与安静私密洽谈需要区分空间边界",
                   "resolution": "pending", "source_refs": []}],
    "open_questions": [],
    "cost": {"budget": {"value": None, "unit": "CNY", "known_status": "unknown", "source_refs": []},
             "known_items": [], "unknown_items": [{"statement": "材料单价与价源", "value": None,
                                                    "known_status": "unknown", "source_refs": []}]},
    "source_refs": [{"source_id": "synthetic-input"}],
    "project_context": {"source_status": "synthetic_input_only"},
}
site = {"width": "12", "length": "8", "boundary_source": "test_parameters_not_site_verified",
        "obstacles": []}
try:
    models = provider.generate(set_id="probe-set-1", brief=brief, site=site,
                               input_hash="a" * 64, generated_at="2026-11-09T00:00:00+00:00")
    print("MODELS", len(models))
    for model in models:
        validate_model(model)
        print(json.dumps({
            "strategy_id": model["strategy"]["strategy_id"],
            "circulation": model["circulation"]["kind"],
            "entrance": model["boundary"]["entrance"]["side"],
            "objects": len(model["objects"]),
            "zones": [obj["name"] for obj in model["objects"] if obj["kind"] == "functional_zone"],
            "statement": model["strategy"]["statement"][:220],
            "tradeoffs": model["strategy"]["tradeoffs"][:3],
            "materials": [item["material_id"] for item in model["materials"]],
            "paths": len(model["circulation"]["segments"]),
            "zone_roles": [obj.get("properties", {}).get("zone_role") for obj in model["objects"]
                           if obj["kind"] == "functional_zone"],
            "furniture": [obj.get("properties", {}).get("furniture_type") for obj in model["objects"]
                          if obj["kind"] == "display_object"],
            "walls": len([obj for obj in model["objects"] if obj["kind"] == "partition"]),
            "focal": len([obj for obj in model["objects"] if obj.get("properties", {}).get("focal")]),
        }, ensure_ascii=False))
    print("DIFFERENT", candidates_are_structurally_different(models[0], models[1]))
    print("RUNS", json.dumps(provider.runs, ensure_ascii=False)[:1600])
except Exception as error:
    print("FAILED", type(error).__name__, str(error)[:900])
    print("RUNS", json.dumps(provider.runs, ensure_ascii=False)[:1600])
    raise SystemExit(1)
