"""W3 Astra review (R1—R5) regression gates.

These tests are the in-repo regression counterpart of
``scripts/w3_astra_findings.py``.  They fail on the frozen 72442c7 baseline and
pass on the remediated tree.  Everything is local: an injected protocol stub,
an isolated SQLite file and a stub renderer.  No paid model call and no real key.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "mvp", ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rkd_mvp import realmodel_spatial_adapter as A  # noqa: E402
from rkd_mvp import site_snapshot as SS  # noqa: E402
from rkd_mvp.admission import (  # noqa: E402
    _origin_consistency_problems, admit_document, geometry_projection_digest)
from rkd_mvp.ai_design_option_provider import DesignOptionConfig, RealModelDesignOptionProvider  # noqa: E402
from rkd_mvp.ai_spatial_outputs import completeness_for_render  # noqa: E402
from rkd_mvp.controlled_run_ledger import ControlledRunService, ControlledExecutionError  # noqa: E402
from w3_trust_findings import CapturingOpener, candidate  # noqa: E402

BASEMAP = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"
PROJECT = "ningbo-xiecheng"
ORG = "org-local"


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(value) -> str:
    return hashlib.sha256(canon(value)).hexdigest()


def config() -> DesignOptionConfig:
    return DesignOptionConfig(
        kind="openai_compatible", name="stub", adapter_version="stub", prompt_version="pv",
        schema_version="rkd-ai-design-option.v1", max_candidates=2, real_model=True,
        configuration_errors=[], base_url="http://127.0.0.1:9/stub", model_id="stub-model",
        api_key_present=True, max_attempts=2, timeout_seconds=5, external_context_allowed=False)


class StubOpener:
    def __init__(self) -> None:
        self.inner = CapturingOpener({"branch": candidate("branch", 10.3),
                                      "loop": candidate("loop", 10.3)})

    def open(self, request, timeout=None):
        return self.inner.open(request, timeout=timeout)


class AstraR2Tests(unittest.TestCase):
    def test_self_reported_live_http_cannot_issue_real_run(self):
        service = ControlledRunService(Path(tempfile.mkdtemp()) / "runs")
        with self.assertRaises(ControlledExecutionError) as error:
            service.observe_exchange(
                project_id=PROJECT, transport="live_http",
                endpoint="https://public.example.com/v1",
                request_bytes=b"x", response_bytes=b"y")
        self.assertEqual(error.exception.code, "OBSERVE_EXCHANGE_CLOSED")
        self.assertEqual(service.export_public(), [])


class AstraR4Tests(unittest.TestCase):
    def test_rect_rebuilt_from_actual_geometry(self):
        facts = A._load_basemap_facts(BASEMAP)
        snap = SS.build_snapshot(facts=facts, entrance_point_m=[0, 10.3],
                                 entrance_reason="regression")
        psite = SS.provider_site(snap)
        opener = StubOpener()
        provider = RealModelDesignOptionProvider(config(), api_key="stub",
                                                 opener=opener)
        models = provider.generate(
            set_id="r4", brief={"requirements": [], "design_intent": [], "conflicts": [],
                                "cost": {"known_items": [], "unknown_items": []}},
            site=psite, input_hash=snap["sha256"], generated_at="2026-01-01T00:00:00+00:00")
        cand, _ = A.candidate_from_persisted(models[0])
        doc = A.adapt_candidate(
            cand, site=SS.adapter_site(snap), basemap_dir=BASEMAP,
            provenance={"sha256": sha(cand), "model_site_boundary_m": [26.17, 17.92],
                        "project_id": PROJECT, "provider_kind": "local_protocol_stub",
                        "site_snapshot_sha256": snap["sha256"]},
            created_at="2026-01-01T00:00:00+00:00")
        self.assertEqual(A.verify_geometry_projection_consistency(doc)["status"], "consistent")
        axes = {item["axis"] for item in doc["spatial"]["circulation"]}
        self.assertTrue({"horizontal", "vertical"}.issubset(axes))
        tampered = copy.deepcopy(doc)
        tampered["spatial"]["circulation"][0]["path_mm"] = [
            [p[0] + 100000, p[1]] for p in tampered["spatial"]["circulation"][0]["path_mm"]]
        with self.assertRaises(A.RealModelSpatialAdaptationError) as error:
            A.verify_geometry_projection_consistency(tampered)
        self.assertEqual(error.exception.code, "GEOMETRY_PROJECTION_INCONSISTENT")


class AstraR3DeclarationTests(unittest.TestCase):
    def test_real_model_declaration_conflict_rejected(self):
        doc = {"generation": {"real_model": True},
               "spatial": {"source": {"origin_kind": "fixture_shape",
                                      "design_origin": {"kind": "fixture"}},
                           "adaptation": {"source_verification": {"generation_real_model": False}}}}
        problems = _origin_consistency_problems(doc)
        self.assertTrue(problems)
        self.assertTrue(any("design_origin.kind" in item for item in problems))
        self.assertNotEqual(geometry_projection_digest({"spatial": {"zones": [1]}}),
                            geometry_projection_digest({"spatial": {"zones": [2]}}))


class AstraR5Tests(unittest.TestCase):
    def test_completeness_is_explicit_for_no_render(self):
        complete = completeness_for_render("rendered", render_present=True)
        preview = completeness_for_render("not_run", render_present=False)
        failed = completeness_for_render("failed", render_present=False)
        cancelled = completeness_for_render("cancelled", render_present=False)
        self.assertEqual(complete["status"], "complete")
        for item in (preview, failed, cancelled):
            self.assertEqual(item["status"], "incomplete")
            self.assertIn("preview", item["reason"])


if __name__ == "__main__":
    unittest.main()
