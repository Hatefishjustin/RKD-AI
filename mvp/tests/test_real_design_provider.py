"""Real-model design provider: local protocol stubs, no network or billing.

These tests prove that a real model channel is required, that failures are
visible and never silently fall back to the synthetic adapter, and that a
real-model candidate passes the same versioned contract and geometry checks.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError, URLError

from rkd_mvp.ai_design_option_provider import (DesignOptionConfig, DesignOptionProviderFailure,
                                               RealModelDesignOptionProvider, build_design_option_provider,
                                               load_design_option_config)
from rkd_mvp.ai_design_option_service import AIDesignOptionService
from rkd_mvp.ai_design_geometry import candidates_are_structurally_different, validate_model
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository
from rkd_mvp.sqlite_store import SQLiteStore

ROOT = Path(__file__).parents[2]
ORG, PROJECT = "org-real-test", "project-real-test"


def real_env(**overrides):
    env = {"RKD_AI_PROVIDER": "openai-compatible", "RKD_AI_DESIGN_PROVIDER": "openai-compatible",
           "RKD_AI_BASE_URL": "https://example.invalid/v1", "RKD_AI_MODEL": "stub-model",
           "RKD_AI_API_KEY": "stub-key-not-a-secret", "RKD_AI_EXTERNAL_CONTEXT": "false",
           "RKD_AI_DESIGN_MAX_ATTEMPTS": "2", "RKD_AI_TIMEOUT_SECONDS": "30"}
    env.update(overrides)
    return env


def legal_candidate(strategy_id: str, branch: bool) -> dict:
    if branch:
        paths = [{"segment_id": "path-south", "x": 0, "y": 0.4, "width": 12, "length": 1.2},
                 {"segment_id": "path-spine", "x": 5.4, "y": 0.4, "width": 1.2, "length": 6.4}]
        connections = [["path-south", "path-spine"]]
        zones = [
            {"object_id": "zone:a", "name": "接待区", "x": 1.0, "y": 1.6, "width": 4.0,
             "length": 4.0, "material_id": "mat-warm", "min_area_m2": "4"},
            {"object_id": "zone:b", "name": "展示区", "x": 6.6, "y": 1.6, "width": 2.0,
             "length": 4.0, "material_id": "mat-warm", "min_area_m2": "4"},
            {"object_id": "zone:c", "name": "洽谈区", "x": 8.6, "y": 1.6, "width": 2.0,
             "length": 4.0, "material_id": "mat-neutral", "min_area_m2": "4"},
        ]
    else:
        paths = [{"segment_id": "path-south", "x": 0, "y": 0.4, "width": 12, "length": 1.2},
                 {"segment_id": "path-west", "x": 2.4, "y": 0.4, "width": 1.2, "length": 6.4},
                 {"segment_id": "path-east", "x": 8.8, "y": 0.4, "width": 1.2, "length": 6.4},
                 {"segment_id": "path-north", "x": 2.4, "y": 5.6, "width": 7.6, "length": 1.2}]
        connections = [["path-south", "path-west"], ["path-south", "path-east"],
                       ["path-west", "path-north"], ["path-east", "path-north"]]
        zones = [
            {"object_id": "zone:a", "name": "接待区", "x": 3.6, "y": 1.6, "width": 2.0,
             "length": 4.0, "material_id": "mat-warm", "min_area_m2": "4"},
            {"object_id": "zone:b", "name": "中央展示", "x": 5.6, "y": 1.6, "width": 1.6,
             "length": 4.0, "material_id": "mat-warm", "min_area_m2": "4"},
            {"object_id": "zone:c", "name": "洽谈区", "x": 7.2, "y": 1.6, "width": 1.6,
             "length": 4.0, "material_id": "mat-neutral", "min_area_m2": "4"},
        ]
    return {
        "strategy_id": strategy_id, "concept": "真实模型概念", "statement": "空间组织说明",
        "rationale": "回应需求与取舍", "tradeoffs": ["取舍一", "取舍二"],
        "entrance_side": "left", "circulation_kind": "branch" if branch else "loop",
        "materials": [{"material_id": "mat-warm", "name": "暖木意向", "intent": "未选产品"}],
        "zones": zones, "displays": [], "partitions": [], "entrance_buffers": [],
        "paths": paths, "connections": connections, "relationships": [],
        "cost_unknown": ["材料单价与价源"],
    }


class FakeResponse:
    def __init__(self, data: bytes, headers: dict | None = None) -> None:
        self.data, self.headers = data, headers or {"X-Request-Id": "stub-request"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _size=None):
        return self.data


class FakeOpener:
    def __init__(self, payloads: list[dict | str], *, error: Exception | None = None) -> None:
        self.payloads, self.error, self.calls = payloads, error, []

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        item = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        content = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        response = {"model": "stub-model", "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                                                       "total_tokens": 150},
                    "choices": [{"message": {"content": content}}]}
        return FakeResponse(json.dumps(response, ensure_ascii=False).encode("utf-8"))


class RealDesignProviderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.env = real_env()
        self.config = load_design_option_config(self.env)
        self.brief = {
            "requirements": [{"statement": "开放交流，入口在左侧，暖木色，保留独立洽谈"}],
            "design_intent": [{"statement": "更开放的展示关系"}], "conflicts": [], "open_questions": [],
            "cost": {"budget": {"value": None, "unit": "CNY", "known_status": "unknown", "source_refs": []},
                     "known_items": [], "unknown_items": []},
            "source_refs": [{"source_id": "synthetic-input"}],
            "project_context": {"source_status": "synthetic_input_only"},
        }
        self.site = {"width": "12", "length": "8", "boundary_source": "test_parameters_not_site_verified",
                     "obstacles": []}

    def tearDown(self):
        self.directory.cleanup()

    def provider(self, payloads, *, error=None, env=None, config=None):
        resolved = config or self.config
        effective_env = env or self.env
        return RealModelDesignOptionProvider(
            resolved, effective_env.get("RKD_AI_API_KEY", ""), opener=FakeOpener(payloads, error=error),
            environ=effective_env, run_log_dir=self.root / "runs")

    def test_configuration_requires_real_channel_and_never_serialises_key(self):
        self.assertEqual(self.config.kind, "openai_compatible")
        self.assertTrue(self.config.real_model)
        self.assertEqual(self.config.configuration_errors, [])
        self.assertNotIn("stub-key-not-a-secret", json.dumps(self.config.public()))
        missing = load_design_option_config(real_env(RKD_AI_API_KEY=""))
        self.assertTrue(missing.configuration_errors)
        with self.assertRaises(DesignOptionProviderFailure) as error:
            self.provider([{}], config=missing).generate(
                set_id="s1", brief=self.brief, site=self.site, input_hash="a" * 64,
                generated_at="2026-11-09T00:00:00+00:00")
        self.assertEqual(error.exception.code, "DESIGN_PROVIDER_NOT_CONFIGURED")

    def test_real_model_produces_two_different_contract_valid_designs(self):
        payload = {"candidates": [legal_candidate("loop-a", False), legal_candidate("branch-b", True)]}
        provider = self.provider([payload])
        models = provider.generate(set_id="s1", brief=self.brief, site=self.site,
                                   input_hash="a" * 64, generated_at="2026-11-09T00:00:00+00:00")
        self.assertEqual(len(models), 2)
        for model in models:
            self.assertTrue(model["generation"]["real_model"])
            self.assertEqual(model["source_kind"], "real_model")
            self.assertEqual(model["generation"]["model_id"], "stub-model")
            validate_model(model)
        self.assertTrue(candidates_are_structurally_different(models[0], models[1]))
        self.assertTrue(any(run["status"] == "succeeded" for run in provider.runs))
        ledger = self.root / "runs" / "design-model-runs.jsonl"
        self.assertTrue(ledger.is_file())
        self.assertNotIn("stub-key-not-a-secret", ledger.read_text(encoding="utf-8"))

    def test_http_authorization_failure_is_visible_and_not_retried_as_synthetic(self):
        error = HTTPError("https://example.invalid/v1/chat/completions", 401, "unauthorized", {}, None)
        provider = self.provider([{}], error=error)
        with self.assertRaises(DesignOptionProviderFailure) as failure:
            provider.generate(set_id="s1", brief=self.brief, site=self.site,
                              input_hash="a" * 64, generated_at="2026-11-09T00:00:00+00:00")
        self.assertEqual(failure.exception.code, "PROVIDER_HTTP_401")
        self.assertEqual(failure.exception.category, "authorization")
        self.assertTrue(any(run.get("error_code") == "PROVIDER_HTTP_401" for run in provider.runs))

    def test_timeout_records_pending_reconciliation_and_no_result(self):
        provider = self.provider([{}], error=URLError("timed out"))
        with self.assertRaises(DesignOptionProviderFailure) as failure:
            provider.generate(set_id="s1", brief=self.brief, site=self.site,
                              input_hash="a" * 64, generated_at="2026-11-09T00:00:00+00:00")
        self.assertEqual(failure.exception.code, "PROVIDER_TIMEOUT")
        timed_out = next(run for run in provider.runs if run.get("error_code") == "PROVIDER_TIMEOUT")
        self.assertEqual(timed_out["cost"]["cost_known_status"], "pending_reconciliation")

    def test_malformed_output_is_rejected_without_writing_candidates(self):
        provider = self.provider(["not-json-at-all"])
        with self.assertRaises(DesignOptionProviderFailure) as failure:
            provider.generate(set_id="s1", brief=self.brief, site=self.site,
                              input_hash="a" * 64, generated_at="2026-11-09T00:00:00+00:00")
        self.assertEqual(failure.exception.code, "MALFORMED_DESIGN_JSON")

    def test_homogeneous_candidates_are_returned_to_designer_then_rejected(self):
        same = legal_candidate("same", False)
        payload = {"candidates": [same, json.loads(json.dumps(same))]}
        provider = self.provider([payload, payload])
        with self.assertRaises(DesignOptionProviderFailure) as failure:
            provider.generate(set_id="s1", brief=self.brief, site=self.site,
                              input_hash="a" * 64, generated_at="2026-11-09T00:00:00+00:00")
        self.assertEqual(failure.exception.code, "MODEL_GEOMETRY_UNRESOLVED")
        self.assertTrue(any(run["kind"] == "design_options.review_failed" for run in provider.runs))
        self.assertFalse(any(run["kind"] == "design_options.accepted" for run in provider.runs))

    def test_service_accepts_real_model_generation_metadata(self):
        payload = {"candidates": [legal_candidate("loop-a", False), legal_candidate("branch-b", True)]}
        provider = self.provider([payload])
        db = self.root / "app.sqlite3"
        SQLiteStore(db).close()
        service = AIDesignOptionService(
            SQLiteAIDesignOptionRepository(db), lambda org, project: None,
            lambda org, project: self.site, self.root, config=self.config,
            provider=provider, start_workers=False)
        input_hash = "b" * 64
        models = provider.generate(set_id="s1", brief=self.brief, site=self.site,
                                   input_hash=input_hash, generated_at="2026-11-09T00:00:00+00:00")
        for model in models:
            checked = service._validate_candidate(model, brief=self.brief, config=self.config,
                                                  input_hash=input_hash)
            self.assertEqual(checked["validation"]["status"], "passed")
            self.assertTrue(checked["generation"]["real_model"])
        self.assertTrue(service.status(ORG, PROJECT)["configured"])

    def test_build_provider_never_returns_synthetic_for_real_config(self):
        built = build_design_option_provider(self.config, environ=self.env)
        self.assertIsInstance(built, RealModelDesignOptionProvider)


if __name__ == "__main__":
    unittest.main()
