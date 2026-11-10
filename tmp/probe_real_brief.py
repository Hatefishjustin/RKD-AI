"""Diagnose real-model brief output against the versioned schema."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))

from jsonschema import Draft202012Validator  # noqa: E402
from rkd_mvp.ai_model_provider import OpenAICompatibleProvider, load_provider_config  # noqa: E402

key = os.environ["RKD_TEST_KEY"]
env = {"RKD_AI_PROVIDER": "openai-compatible", "RKD_AI_BASE_URL": "https://api.codelink.chat/v1",
       "RKD_AI_MODEL": "gpt-5.6-sol", "RKD_AI_API_KEY": key,
       "RKD_AI_EXTERNAL_CONTEXT": "false", "RKD_AI_TIMEOUT_SECONDS": "120"}
config = load_provider_config(env)
provider = OpenAICompatibleProvider(config, key)
manifest = {
    "schema_version": "rkd-ai-context-manifest.v1", "requirement_id": "probe-req", "requirement_revision_no": 1,
    "source_refs": [{"source_id": "synthetic-input", "origin_kind": "manual_input",
                     "locator": "request.natural_language", "content_status": "provided",
                     "evidence_status": "unverified"}],
    "project_context": {"project_type": "unknown", "service_scope": "内部设计草稿；项目资料未获准外发",
                        "budget": {"value": None, "unit": "CNY", "known_status": "unknown",
                                   "source_refs": [], "unknown_reason": "项目资料未获准外发"},
                        "excluded_scopes": [], "source_status": "synthetic_input_only"},
    "source_conflicts": [], "content_reading": "synthetic_input_only",
    "external_project_context_allowed": False,
}
result = provider.generate(text="开放交流与展示，入口在左侧，暖木色，保留独立洽谈",
                           manifest=manifest, input_hash="a" * 64,
                           config_hash=config.fingerprint(), generated_at="2026-11-09T00:00:00+00:00")
brief = result.brief
print("TOP KEYS", sorted(brief.keys()))
print("RAW", json.dumps(brief, ensure_ascii=False)[:3000])
schema = json.loads((ROOT / "contracts/v1/ai-design-brief.schema.json").read_text(encoding="utf-8"))
errors = sorted(Draft202012Validator(schema).iter_errors(brief), key=lambda e: list(e.path))
for error in errors[:20]:
    print("ERROR", list(error.path), error.message[:220])
print("ERROR COUNT", len(errors))
