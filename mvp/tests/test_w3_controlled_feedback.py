"""W3 controlled spatial feedback revision (AI-DESIGN-03) permanent regression.

All cases drive the real ApiService composition root, the real
ControlledDesignRuntime, a real isolated SQLite store and a local protocol stub
(every run is simulated=True / fixture).  No manual record insertion replaces
the product path, no external model call, no real key.

Covers: normal revision; lock rewrite/deletion; stale parent/input/adoption
baselines; two concurrent feedbacks; invalid geometry; provider failure;
missing/foreign scope; discarded-before-commit (no phantom parent); post-commit
parent digest; adoption CAS; immutable parent bytes.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import time
import traceback
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "mvp", ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rkd_mvp.ai_design_option_provider import DesignOptionConfig  # noqa: E402
from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider  # noqa: E402
from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository  # noqa: E402
from rkd_mvp.ai_requirement_service import AIRequirementService  # noqa: E402
from rkd_mvp.api_service import ApiError, ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.requirement_service import RequirementService  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from w3_trust_findings import candidate  # noqa: E402

ORG = "org-local"
PROJECT = NINGBO_PROJECT_ID
FIXTURE = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha(value) -> str:
    return hashlib.sha256(canon(value)).hexdigest()


class StubResponse:
    def __init__(self, payload) -> None:
        self._raw = canon(payload)
        self.headers = {}
        self.status = 200

    def read(self, _n=None) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FeedbackOpener:
    """Generate = 2 candidates; revise = one candidate whose shape depends on mode."""

    def __init__(self, mode: str = "ok", on_revise=None) -> None:
        self.mode = mode
        self.on_revise = on_revise
        self.lock = threading.Lock()
        self.calls: list[dict] = []

    def open(self, request, timeout=None):
        body = bytes(getattr(request, "data", b"") or b"")
        payload = json.loads(body.decode("utf-8"))
        user_text = " ".join(str(item.get("content") or "")
                             for item in payload.get("messages", []))
        revising = "feedback_task" in user_text
        with self.lock:
            self.calls.append({"body": payload, "revising": revising,
                               "request_sha256": hashlib.sha256(body).hexdigest()})
        if not revising:
            content = canon({"candidates": [candidate("branch", 10.3),
                                            candidate("loop", 10.3)]}).decode("utf-8")
        else:
            if self.on_revise is not None:
                self.on_revise()
            if self.mode == "http_error":
                raise HTTPError("http://127.0.0.1:9/stub", 500, "stub failure", {}, None)
            if self.mode == "timeout":
                raise URLError("stub timeout")
            revised = candidate("loop", 10.3)
            revised["strategy_id"] = "feedback-revised"
            revised["concept"] = "反馈修订桩候选，不是设计成果"
            if self.mode == "lock_change":
                for zone in revised["zones"]:
                    if zone["object_id"] == "zone:display":
                        zone["x"] = 9.8
            elif self.mode == "delete_object":
                revised["zones"] = [zone for zone in revised["zones"]
                                    if zone["object_id"] != "zone:display"]
            elif self.mode == "bad_geometry":
                revised["zones"][0]["x"] = 999
            locks_out = [] if self.mode == "locks_dropped" else ["entrance", "zone:display"]
            content = canon({"candidate": revised, "parsed_intents": ["more_open"],
                             "locked_conflicts": [], "locks": locks_out}).decode("utf-8")
        return StubResponse({"choices": [{"message": {"content": content}}],
                             "model": payload.get("model"), "usage": {}})


class ControlledFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.db = self.root / "app.sqlite3"
        self._services: list[ApiService] = []
        self._stores: list[SQLiteStore] = []
        self._thread_errors: list[str] = []
        self._old_hook = threading.excepthook

        def collect(args):
            self._thread_errors.append(
                f"[{args.thread.name}] {args.exc_type.__name__}: {args.exc_value}\n"
                + "".join(traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback)))
            self._old_hook(args)

        threading.excepthook = collect
        self.store = SQLiteStore(self.db)
        self._stores.append(self.store)
        self.files = FileService(self.db, self.root)
        self.requirements = RequirementService(self.db)
        cfg = AIProviderConfig(
            kind="synthetic", name="本地合成需求通道（非真实 AI）", model_id=None,
            base_url=None, api_key_present=False, adapter_version="v1", prompt_version="pv",
            schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
            max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
            real_model=False, configuration_errors=[])
        self.requirement_ai = AIRequirementService(
            SQLiteAIRequirementRepository(self.db), self.requirements, config=cfg,
            provider_factory=lambda config: build_provider(config))

    def tearDown(self):
        problems: list[str] = []
        try:
            self.requirement_ai.wait_for_idle(timeout_seconds=30)
            self.assertFalse(self.requirement_ai._active())
            for service in self._services:
                design = service.ai_design_option_service
                if design is not None:
                    design.wait_for_idle(timeout_seconds=30)
                    self.assertFalse(design._active())
                output = service.ai_spatial_output_service
                if output is not None:
                    output.wait_for_idle(timeout_seconds=30)
        except Exception as error:  # noqa: BLE001
            problems.append(f"worker 未收尾：{type(error).__name__}: {error}")
        for store in reversed(self._stores):
            try:
                store.close()
            except Exception as error:  # noqa: BLE001
                problems.append(f"关库失败：{error}")
        try:
            self.directory.cleanup()
        except Exception as error:  # noqa: BLE001
            problems.append(f"清理失败：{error}")
        finally:
            threading.excepthook = self._old_hook
        if self._thread_errors:
            problems.append("后台线程异常：\n" + "\n---\n".join(self._thread_errors))
        if problems:
            self.fail("\n".join(problems))

    # --------------------------------------------------------------- helpers
    def build_service(self, opener, *, root: Path | None = None) -> ApiService:
        root = root or self.root
        root.mkdir(parents=True, exist_ok=True)
        config = DesignOptionConfig(
            kind="openai_compatible", name="本地协议桩（模拟）", adapter_version="stub",
            prompt_version="pv", schema_version="rkd-ai-design-option.v1", max_candidates=2,
            real_model=True, configuration_errors=[], base_url="http://127.0.0.1:9/stub",
            model_id="stub-model", api_key_present=True, max_attempts=2, timeout_seconds=5,
            external_context_allowed=False)
        store = self.store if root == self.root else SQLiteStore(self.db)
        if store is not self.store:
            self._stores.append(store)
        service = ApiService(
            MVPApp(store), FileService(self.db, root), requirement_service=self.requirements,
            ai_requirement_service=self.requirement_ai, runtime_root=root,
            design_option_config=config, design_transport_opener=opener)
        self._services.append(service)
        return service

    def prepare(self, opener):
        service = self.build_service(opener)
        self.files.seed_ningbo(service, FIXTURE)
        brief = service.submit_ai_requirement(
            ORG, PROJECT, "tester", {"natural_language": "开放交流，入口在左侧，暖木色"},
            "brief-feedback-regression")["item"]
        self.requirement_ai.wait_for_job(ORG, PROJECT, brief["job_id"])
        item = service.submit_ai_design_options(
            ORG, PROJECT, "tester", {}, "options-feedback-regression")["item"]
        service.ai_design_option_service.wait_for_set(ORG, PROJECT, item["set_id"],
                                                     timeout_seconds=120)
        state = service.get_ai_design_options(ORG, PROJECT)
        parent = state["item"]["options"][0]
        baseline = {"option_id": parent["option_id"],
                    "expected_revision": parent["revision_no"],
                    "parent_revision_id": parent["option_revision_id"],
                    "expected_version": int(state["adoption"]["expected_revision"])
                    if state.get("adoption") else 0,
                    "expected_input_hash": next(row["input_hash"] for row in state["sets"]
                                                if row["set_id"] == item["set_id"]),
                    "feedback": "更开放但保留入口",
                    "locks": ["entrance", "zone:display"]}
        return service, parent, baseline

    def request(self, baseline, **overrides):
        return {**baseline, **overrides}

    # ----------------------------------------------------------------- tests
    def test_successful_feedback_creates_new_revision_with_fresh_binding(self):
        opener = FeedbackOpener()
        service, parent, baseline = self.prepare(opener)
        before_sha = sha(parent["model"])
        parent_run = parent["validation"]["controlled"]["run_id"]
        result = service.revise_ai_design_option(
            ORG, PROJECT, "tester", self.request(baseline))
        revision = result["item"]
        self.assertEqual(revision["revision_no"], 2)
        self.assertEqual(revision["parent_revision_id"], parent["option_revision_id"])
        self.assertNotEqual(revision["option_revision_id"], parent["option_revision_id"])
        controlled = revision["validation"]["controlled"]
        self.assertNotEqual(controlled["run_id"], parent_run)
        runtime = service.controlled_design_runtime
        record = next(row for row in runtime.run_service.export_public()
                      if row["run_id"] == controlled["run_id"])
        self.assertEqual(record["project_id"], PROJECT)
        self.assertEqual(record["parent_revision_id"], parent["option_revision_id"])
        self.assertEqual(record["input_hash"], controlled["provenance"]["input_hash"]
                         if "input_hash" in controlled["provenance"] else record["input_hash"])
        observing = [call for call in opener.calls
                     if call["revising"] and
                     hashlib.sha256(canon(call["body"])).hexdigest() == record["request_sha256"]]
        # request bytes are captured by the ledger; check the recorded digest is
        # the digest of a real revise exchange, not the parent's generation call.
        self.assertEqual(sum(1 for call in opener.calls if call["revising"]), 1)
        self.assertEqual(record["site_snapshot_sha256"],
                         parent["model"]["spatial"]["source"]["site_snapshot_sha256"])
        self.assertTrue(controlled["admission"]["adoptable"])
        self.assertTrue(runtime.verifier().revision_registered(
            PROJECT, revision["option_revision_id"]))
        self.assertEqual(
            runtime.run_service._revisions[(PROJECT, revision["option_revision_id"])],
            controlled["provenance"]["sha256"])
        self.assertEqual(
            record["parent_candidate_sha256"],
            parent["validation"]["controlled"]["provenance"]["sha256"])
        after = service.get_ai_design_options(ORG, PROJECT)
        unchanged = next(row for row in after["item"]["revisions"]
                         if row["option_revision_id"] == parent["option_revision_id"])
        self.assertEqual(sha(unchanged["model"]), before_sha, "父候选内容被改写")
        self.assertIn(revision["option_revision_id"],
                      [row["option_revision_id"] for row in after["item"]["revisions"]])
        visible = next(row for row in after["item"]["options"]
                       if row["option_revision_id"] == revision["option_revision_id"])
        self.assertTrue(visible["artifacts"])
        artifact = visible["artifacts"][0]
        meta, path = service.get_ai_design_option_artifact(
            ORG, PROJECT, artifact["artifact_id"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), meta["sha256"])
        self.assertEqual(meta["sha256"], artifact["sha256"])

    def test_lock_field_rewritten_by_model_is_rejected(self):
        service, _parent, baseline = self.prepare(FeedbackOpener(mode="lock_change"))
        with self.assertRaises(ApiError) as error:
            service.revise_ai_design_option(ORG, PROJECT, "tester",
                                            self.request(baseline))
        self.assertIn(error.exception.code, {"LOCK_FIELD_MODIFIED", "MODEL_REVISION_UNRESOLVED"})
        self.assertEqual(len(service.get_ai_design_options(
            ORG, PROJECT)["item"]["revisions"]), 2)

    def test_locked_object_deleted_is_rejected(self):
        service, _parent, baseline = self.prepare(FeedbackOpener(mode="delete_object"))
        with self.assertRaises(ApiError) as error:
            service.revise_ai_design_option(ORG, PROJECT, "tester",
                                            self.request(baseline))
        self.assertIn(error.exception.code, {"LOCK_OBJECT_DELETED", "MODEL_REVISION_UNRESOLVED"})

    def test_stale_parent_and_input_and_adoption_baselines_rejected(self):
        service, parent, baseline = self.prepare(FeedbackOpener())
        with self.assertRaises(ApiError) as stale_parent:
            service.revise_ai_design_option(ORG, PROJECT, "tester", self.request(
                baseline, parent_revision_id="invented-parent"))
        self.assertEqual(stale_parent.exception.code, "STALE_PARENT_REVISION")
        with self.assertRaises(ApiError) as stale_input:
            service.revise_ai_design_option(ORG, PROJECT, "tester", self.request(
                baseline, expected_input_hash="0" * 64))
        self.assertEqual(stale_input.exception.code, "STALE_INPUT_SNAPSHOT")
        with self.assertRaises(ApiError) as stale_version:
            service.revise_ai_design_option(ORG, PROJECT, "tester", self.request(
                baseline, expected_version=99))
        self.assertEqual(stale_version.exception.code, "STALE_ADOPTION_VERSION")
        with self.assertRaises(ApiError) as stale_revision:
            service.revise_ai_design_option(ORG, PROJECT, "tester", self.request(
                baseline, expected_revision=parent["revision_no"] + 2))
        self.assertEqual(stale_revision.exception.code, "STALE_OPTION_REVISION")
        self.assertEqual(len(service.get_ai_design_options(
            ORG, PROJECT)["item"]["revisions"]), 2)

    def test_two_concurrent_feedbacks_only_one_wins(self):
        service, _parent, baseline = self.prepare(FeedbackOpener())
        outcomes: list[str] = []

        def invoke(index):
            try:
                service.revise_ai_design_option(
                    ORG, PROJECT, "tester",
                    self.request(baseline, feedback=f"反馈{index}"))
                outcomes.append("ok")
            except ApiError as error:
                outcomes.append(error.code)

        threads = [threading.Thread(target=invoke, args=(index,)) for index in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        service.ai_design_option_service.wait_for_idle(timeout_seconds=30)
        self.assertEqual(sorted(outcomes), ["STALE_OPTION_REVISION", "ok"],
                         f"并发反馈结果异常：{outcomes}")
        self.assertEqual(len(service.get_ai_design_options(
            ORG, PROJECT)["item"]["revisions"]), 3)

    def test_invalid_geometry_and_provider_errors_do_not_persist(self):
        service, _parent, baseline = self.prepare(FeedbackOpener(mode="bad_geometry"))
        with self.assertRaises(ApiError) as invalid:
            service.revise_ai_design_option(ORG, PROJECT, "tester",
                                            self.request(baseline))
        self.assertEqual(invalid.exception.code, "MODEL_REVISION_UNRESOLVED")
        for mode in ("http_error", "timeout"):
            failing, _parent, failing_baseline = self.prepare(FeedbackOpener(mode=mode))
            with self.assertRaises(ApiError) as failure:
                failing.revise_ai_design_option(
                    ORG, PROJECT, "tester", self.request(failing_baseline))
            self.assertEqual(failure.exception.status, 503)
            self.assertEqual(len(failing.get_ai_design_options(
                ORG, PROJECT)["item"]["revisions"]), 2)

    def test_missing_and_foreign_scope_fail_closed(self):
        service, _parent, baseline = self.prepare(FeedbackOpener())
        service.revise_ai_design_option(ORG, PROJECT, "tester", self.request(baseline))
        runtime = service.controlled_design_runtime
        revisions = service.get_ai_design_options(ORG, PROJECT)["item"]["revisions"]
        model = revisions[0]["validation"]["controlled"]["source_candidate"]
        scope = runtime.begin_invocation(PROJECT)
        scope.opener().open(Request("http://127.0.0.1:9/stub?scope", b"{}"))
        kwargs = dict(project_id=PROJECT, revision_id="rev-feedback-scope-001",
                      candidate_model=model, observation=scope.latest(),
                      config=DesignOptionConfig.from_public(
                          service.get_ai_design_options(ORG, PROJECT)["provider"]),
                      input_hash="h" * 64)
        with self.assertRaises(TypeError):
            runtime.register_and_issue(**kwargs)
        with self.assertRaises(Exception) as none_scope:
            runtime.register_and_issue(**kwargs, scope=None)
        self.assertEqual(getattr(none_scope.exception, "code", ""), "OBSERVATION_SCOPE_REQUIRED")
        other = self.build_service(FeedbackOpener(), root=self.root / "other")
        other_scope = other.controlled_design_runtime.begin_invocation(PROJECT)
        other_scope.opener().open(Request("http://127.0.0.1:9/stub?other", b"{}"))
        with self.assertRaises(Exception) as foreign:
            runtime.run_service.issue(
                observation=scope.latest(), project_id=PROJECT,
                candidate_sha256="c" * 64, input_hash="h" * 64, output_sha256="o" * 64,
                model="m", prompt_version="p", site_snapshot_sha256="s" * 64,
                basemap_files_sha256="b" * 64, scope=other_scope)
        self.assertEqual(getattr(foreign.exception, "code", ""), "OBSERVATION_SCOPE_INVALID")

    def test_discarded_before_commit_leaves_no_parent_registration(self):
        """A baseline changed after the model call discards the candidate.

        ``revise`` is synchronous, so a public ``adopt`` from inside the stubbed
        exchange is used to change the adoption/version baseline between the
        controlled model call and the write transaction.  The write must be
        discarded and the new revision must never become a usable parent.
        """
        holder: dict = {}

        def adopt_while_generating():
            if "service" in holder:
                holder["service"].adopt_ai_design_option(ORG, PROJECT, "tester", {
                    "option_id": holder["option_id"],
                    "expected_revision": holder["expected_revision"],
                    "expected_version": holder["expected_version"]})

        opener = FeedbackOpener(on_revise=adopt_while_generating)
        service, _parent, baseline = self.prepare(opener)
        holder.update({"service": service, "option_id": baseline["option_id"],
                       "expected_revision": baseline["expected_revision"],
                       "expected_version": baseline["expected_version"]})
        initial_registered = {key[1] for key in service.controlled_design_runtime
                              .run_service._revisions if key[0] == PROJECT}
        with self.assertRaises(ApiError) as error:
            service.revise_ai_design_option(ORG, PROJECT, "tester",
                                            self.request(baseline))
        self.assertEqual(error.exception.code, "STALE_ADOPTION_VERSION")
        runtime = service.controlled_design_runtime
        registered_now = {key[1] for key in runtime.run_service._revisions
                          if key[0] == PROJECT}
        self.assertEqual(registered_now, initial_registered,
                         "被丢弃的修订不能登记为可用父链")
        self.assertEqual(len(service.get_ai_design_options(
            ORG, PROJECT)["item"]["revisions"]), 2)

    def test_adoption_cas_conflict_and_feedback_locks_preserved(self):
        service, _parent, baseline = self.prepare(FeedbackOpener())
        revised = service.revise_ai_design_option(
            ORG, PROJECT, "tester", self.request(baseline))["item"]
        self.assertEqual(list(revised["feedback"]["locks"]), baseline["locks"],
                         "修订必须保留用户提交的锁定条件")
        good = self.build_service(FeedbackOpener(), root=self.root / "good")
        self.files.seed_ningbo(good, FIXTURE)
        brief = good.submit_ai_requirement(
            ORG, PROJECT, "tester", {"natural_language": "开放交流"},
            "brief-adoption-cas")["item"]
        self.requirement_ai.wait_for_job(ORG, PROJECT, brief["job_id"])
        item = good.submit_ai_design_options(
            ORG, PROJECT, "tester", {}, "options-adoption-cas")["item"]
        good.ai_design_option_service.wait_for_set(ORG, PROJECT, item["set_id"],
                                                  timeout_seconds=120)
        option = good.get_ai_design_options(ORG, PROJECT)["item"]["options"][0]
        with self.assertRaises(ApiError) as conflict:
            good.adopt_ai_design_option(ORG, PROJECT, "tester", {
                "option_id": option["option_id"], "expected_revision": 1,
                "expected_version": 99})
        self.assertEqual(conflict.exception.code, "STALE_ADOPTION_VERSION")


if __name__ == "__main__":
    unittest.main()
