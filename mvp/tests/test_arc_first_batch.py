"""ARC first-batch regression guards (pure functions, no model calls).

These are deliberately small: the full Q01-Q12 acceptance lives in
scripts/verify_arc_first_batch.py. Here we lock in the defects that were
reproduced before the fix so a future change cannot silently reintroduce them:

  * full contract enforcement instead of a minimum-field gate
  * real shapely intersections instead of bounding boxes
  * a single area-reconciliation basis with explicit unallocated area
  * no character truncation of structured hand-offs
  * substantive candidate difference
  * decision pointers rejected; identity injected by the program
  * append-only gate decisions; seed does not overwrite project facts
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from arc_first_batch_stub import SITE, REQUIREMENT, valid_proposal  # noqa: E402
from rkd_mvp.studio import geometry, orchestrator, revision as R, validation  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402

PROJ = {"id": "ningbo-xiecheng", "name": "宁波", "site": SITE, "requirement": REQUIREMENT}


class ContractEnforcementTest(unittest.TestCase):
    def setUp(self):
        self.base = valid_proposal("A")

    def _validate(self, p, **kw):
        return validation.validate_proposal(p, project=PROJ, option_id="A",
                                            revision=1, parent_revision=None, **kw)

    def test_structure_error_rejected(self):
        p = copy.deepcopy(self.base)
        del p["zones"][0]["role"]
        r = self._validate(p)
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "structure")
        self.assertTrue(any(e["path"] == "/zones/0" and "必填字段" in e["expected"]
                            and "role" in e["expected"] for e in r["errors"]))
        self.assertTrue(all(all(k in e for k in ("path", "expected", "object_id", "hint"))
                            for e in r["errors"]))

    def test_wrong_type_rejected(self):
        p = copy.deepcopy(self.base)
        p["area_table"][0]["area_sqm"] = "one"
        self.assertFalse(self._validate(p)["ok"])

    def test_invalid_catalog_reference_rejected(self):
        p = copy.deepcopy(self.base)
        p["furniture"][0]["catalog_id"] = "ghost-item"
        r = self._validate(p)
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "semantics")
        self.assertTrue(any(e["rule_id"] == "REF-CATALOG" for e in r["errors"]))

    def test_model_cannot_decide_approval_or_adoption(self):
        p = copy.deepcopy(self.base)
        p["approved"] = True
        p["adopt_pointer"] = "A"
        r = self._validate(p)
        self.assertFalse(r["ok"])
        self.assertTrue(any(e["rule_id"] == "IDENTITY-BOUNDARY" for e in r["errors"]))

    def test_identity_is_injected_by_program(self):
        r = self._validate(self.base)
        self.assertTrue(r["ok"])
        self.assertEqual(r["plan"]["project_id"], "ningbo-xiecheng")
        self.assertEqual(r["plan"]["option_id"], "A")
        self.assertEqual(r["plan"]["revision"], 1)
        self.assertEqual(r["plan"]["contract_version"], "rkd-spatial-plan.v1")
        self.assertEqual(r["checks"]["draft_schema_after_assembly"], "passed")
        self.assertEqual(r["status"], "valid_candidate")

    def test_plan_is_valid_is_no_longer_a_minimum_gate(self):
        p = copy.deepcopy(self.base)
        del p["zones"][0]["role"]
        ok, _ = orchestrator.plan_is_valid(p, PROJ)
        self.assertFalse(ok)


class GeometryTest(unittest.TestCase):
    def test_disjoint_triangles_not_reported_as_overlap(self):
        site = {"width_mm": 5000, "height_mm": 5000}
        plan = {"zones": [
            {"id": "A", "name": "A", "role": "gallery",
             "polygon": [[0, 0], [4000, 0], [0, 4000]], "area_sqm": 8},
            {"id": "B", "name": "B", "role": "gallery",
             "polygon": [[4000, 4000], [4000, 500], [500, 4000]], "area_sqm": 6.125}]}
        g = geometry.check_geometry(plan, site)
        self.assertFalse(any(i["rule_id"] == "GEO-004" for i in g["issues"]))

    def test_real_intersection_is_blocker(self):
        site = {"width_mm": 5000, "height_mm": 5000}
        plan = {"zones": [
            {"id": "A", "name": "A", "role": "gallery",
             "polygon": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]], "area_sqm": 4},
            {"id": "B", "name": "B", "role": "gallery",
             "polygon": [[1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000]],
             "area_sqm": 4}]}
        g = geometry.check_geometry(plan, site)
        self.assertFalse(g["ok"])
        self.assertTrue(any(i["rule_id"] == "GEO-004" and i["severity"] == "blocker"
                            for i in g["issues"]))

    def test_100sqm_3sqm_explicitly_reports_97_unallocated(self):
        site = {"width_mm": 10000, "height_mm": 10000}
        plan = {"zones": [
            {"id": "Z1", "name": "Z1", "role": "arrival",
             "polygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]], "area_sqm": 1},
            {"id": "Z2", "name": "Z2", "role": "gallery",
             "polygon": [[2000, 0], [3000, 0], [3000, 1000], [2000, 1000]], "area_sqm": 1},
            {"id": "Z3", "name": "Z3", "role": "meeting",
             "polygon": [[4000, 0], [5000, 0], [5000, 1000], [4000, 1000]], "area_sqm": 1}],
            "area_table": [{"name": "Z1", "area_sqm": 1},
                           {"name": "Z2", "area_sqm": 1},
                           {"name": "Z3", "area_sqm": 1}]}
        g = geometry.check_geometry(plan, site)
        self.assertEqual(g["metrics"]["unallocated_sqm"], 97.0)
        self.assertFalse(g["metrics"]["layout_complete"])
        self.assertFalse(g["ok"])
        self.assertTrue(any("97" in i["message"] for i in g["issues"]))

    def test_complete_layout_reconciles_to_design_scope(self):
        g = geometry.check_geometry(valid_proposal("A"), SITE)
        m = g["metrics"]
        self.assertLess(m["site_area_sqm"], 469.0)  # rounded, not equated
        self.assertGreater(m["design_scope_sqm"], 0)
        self.assertLess(m["design_scope_sqm"], m["site_area_sqm"])
        self.assertTrue(m["layout_complete"])
        self.assertEqual(m["area_reconciliation_basis"], "design_scope_sqm")
        self.assertLess(m["area_reconciliation_gap_sqm"], 1.0)

    def test_reserved_keepout_and_rotated_furniture(self):
        p = valid_proposal("A")
        p["zones"].append({"id": "ZX", "name": "侵入", "role": "support",
                           "polygon": [[22500, 3000], [25500, 3000],
                                       [25500, 7000], [22500, 7000]], "area_sqm": 12})
        g = geometry.check_geometry(p, SITE)
        self.assertTrue(any(i["rule_id"] == "LOCK-001" for i in g["issues"]))


class HandoffTest(unittest.TestCase):
    def test_no_character_truncation_in_orchestrator(self):
        import re
        src = (ROOT / "mvp" / "rkd_mvp" / "studio" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertEqual([l for l in src.splitlines() if re.search(r"\[:\d{4}\]", l)], [])
        p = valid_proposal("A")
        p["open_questions"].append("ZONE_TAIL_SENTINEL " + "事实" * 2000)
        self.assertIn("ZONE_TAIL_SENTINEL", validation.structural_summary(p))

    def test_rename_reorder_and_trivial_shift_are_not_new_topology(self):
        a = valid_proposal("A")
        renamed = copy.deepcopy(a)
        renamed["strategy"]["name"] = "新名字"
        reordered = copy.deepcopy(a)
        reordered["zones"] = list(reversed(reordered["zones"]))
        shifted = copy.deepcopy(a)
        for f in shifted["furniture"]:
            f["x"] += 20
        self.assertFalse(validation.substantive_difference(a, renamed)["substantive"])
        self.assertFalse(validation.substantive_difference(a, reordered)["substantive"])
        self.assertFalse(validation.substantive_difference(a, shifted)["substantive"])
        self.assertTrue(validation.substantive_difference(a, valid_proposal("B"))["substantive"])

    def test_patch_rejects_identity_and_unreasoned_deletion(self):
        base = valid_proposal("A")
        _, errs, _ = R.apply_patch(base, [
            {"op": "update", "group": "zones", "id": "ZA1", "fields": {"approved": True}}])
        self.assertTrue(any(e["rule_id"] in ("PATCH-006", "IDENTITY-BOUNDARY") for e in errs))
        _, errs2, _ = R.apply_patch(base, [
            {"op": "remove", "group": "zones", "id": "ZA4"}])
        self.assertTrue(any(e["rule_id"] == "PATCH-004" for e in errs2))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arc-unit-")
        self.db = Path(self.tmp) / "s.db"
        self.st = Store(self.db)

    def test_decision_replay_cannot_overwrite(self):
        g = self.st.open_gate("p", "title", "detail",
                              baseline_artifact_id="a1", baseline_revision_uid="u1")
        first = self.st.decide_gate(g, "approve", "第一次", "allow_continue")
        second = self.st.decide_gate(g, "reject", "重放", "direction_approval")
        self.assertTrue(first["applied"])
        self.assertFalse(second["applied"])
        self.assertEqual(self.st.gate(g)["decision"], "approve")
        self.assertEqual(self.st.gate(g)["comment"], "第一次")
        self.assertEqual(len(self.st.gate_decisions(g)), 2)

    def test_seed_never_rewrites_existing_facts(self):
        self.st.upsert_project("ningbo-xiecheng", "自定义名称",
                               {"width_mm": 1, "height_mm": 1},
                               {"text": "老板后来改过的需求", "must_have": [],
                                "constraints": {}, "unknowns": []})
        orchestrator.Studio(self.st).seed_from_fixtures()
        p = self.st.get_project("ningbo-xiecheng")
        self.assertEqual(p["name"], "自定义名称")
        self.assertEqual(p["requirement"]["text"], "老板后来改过的需求")

    def test_explicit_project_id_mapping(self):
        self.st.ensure_project("ningbo-xiecheng", "宁波", SITE, REQUIREMENT,
                               source_project_id="project_ningbo_xiecheng_2026")
        self.assertEqual(self.st.resolve_project_id("project_ningbo_xiecheng_2026"),
                         "ningbo-xiecheng")
        self.assertIsNone(self.st.resolve_project_id("unmapped-project"))

    def test_feedback_is_versioned_and_effective(self):
        self.st.ensure_project("p", "P", SITE, REQUIREMENT)
        f1 = self.st.add_feedback("p", "boss_message", "保留入口")
        f2 = self.st.add_feedback("p", "boss_message", "调整洽谈区")
        self.assertEqual(f1["revision_no"], 1)
        self.assertEqual(f2["revision_no"], 2)
        eff = self.st.effective_requirement("p")
        self.assertEqual(len(eff["effective_addenda"]), 2)
        self.assertTrue(self.st.feedback_changed_since("p", 1))
        self.assertFalse(self.st.feedback_changed_since("p", 2))


if __name__ == "__main__":
    unittest.main()
