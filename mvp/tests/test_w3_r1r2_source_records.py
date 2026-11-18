"""W3 来源记录 P1 永久回归：并发观测串线 + 幽灵父修订。

两个缺陷都发生在「候选签发」这一层，所以测试全部走
``ApiService`` 组合根 → 真实 ``ControlledDesignRuntime`` → 真实隔离 SQLite
仓储，不手工插入记录、不调用私有 helper 代替产品入口。

R1 并发串线
    同一项目两个并发 provider invocation，必须以各自的观测签发：每个持久候选的
    run_id、request/response 摘要、input hash、候选摘要都对应自己那次调用；缺失
    观测或用别人的观测必须 fail closed。

R2 幽灵父修订
    候选没有成功写入业务仓储时，账本不得留下可当父链的修订；父链必须只认
    「业务候选已提交」之后的登记。

所有交换都是本地协议桩（``simulated=True``），不外发、不花费用、不用真实密钥。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
import unittest
from pathlib import Path
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "mvp", ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rkd_mvp import realmodel_spatial_adapter as adapter  # noqa: E402
from rkd_mvp.ai_design_option_provider import DesignOptionConfig  # noqa: E402
from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider  # noqa: E402
from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository  # noqa: E402
from rkd_mvp.ai_requirement_service import AIRequirementService  # noqa: E402
from rkd_mvp.api_service import ApiService  # noqa: E402
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


def real_config() -> DesignOptionConfig:
    return DesignOptionConfig(
        kind="openai_compatible", name="本地协议桩（模拟）", adapter_version="stub",
        prompt_version="pv", schema_version="rkd-ai-design-option.v1",
        max_candidates=2, real_model=True, configuration_errors=[],
        base_url="http://127.0.0.1:9/stub", model_id="stub-model",
        api_key_present=True, max_attempts=2, timeout_seconds=5,
        external_context_allowed=False)


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


class PerCallOpener:
    """The Nth exchange gets marker N; the exact bytes are kept for assertions.

    The first response carries a padded field so its parse is slow: the second
    invocation records its exchange while the first is still between "exchange
    recorded" and "observation read".  A project-last binding cannot survive it.
    """

    def __init__(self, pad_first: int = 3_000_000) -> None:
        self.lock = threading.Lock()
        self.calls = 0
        self.pad_first = pad_first
        self.responses: list[bytes] = []
        self.requests: list[bytes] = []
        self.markers: list[str] = []

    def open(self, request, timeout=None):
        body = bytes(getattr(request, "data", b"") or b"")
        with self.lock:
            index = self.calls
            self.calls += 1
            self.requests.append(body)
        marker = "A" if index == 0 else f"B{index}"
        pad = self.pad_first if index == 0 else 0
        branch, loop = candidate("branch", 10.3), candidate("loop", 10.3)
        for item in (branch, loop):
            item["tradeoffs"] = [f"{marker}-invocation", "仅验证工程链"]
            item["concept"] = f"{marker} 桩候选" + ("p" * pad)
        content = canon({"candidates": [branch, loop]}).decode("utf-8")
        response = canon({"choices": [{"message": {"content": content}}],
                          "model": "stub-model", "usage": {}})
        with self.lock:
            self.responses.append(response)
            self.markers.append(marker)
        return StubResponse(json.loads(response))


class BlockingOpener:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def open(self, request, timeout=None):
        self.entered.set()
        self.release.wait(timeout=20)
        content = canon({"candidates": [candidate("branch", 10.3),
                                        candidate("loop", 10.3)]}).decode("utf-8")
        return StubResponse({"choices": [{"message": {"content": content}}],
                             "model": "stub-model", "usage": {}})


class SourceRecordTests(unittest.TestCase):
    """Every case runs through the real composition root and public API."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.db = self.root / "app.sqlite3"
        # Track EVERY service and store created by a test: teardown must wait
        # for their workers before closing connections or deleting the tree.
        self._services: list[ApiService] = []
        self._stores: list[SQLiteStore] = []
        self._thread_exceptions: list[str] = []
        self._old_thread_excepthook = threading.excepthook

        def collect_thread_failure(args):
            self._thread_exceptions.append(
                f"[{args.thread.name}] {args.exc_type.__name__}: {args.exc_value}\n"
                + "".join(traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback)))
            self._old_thread_excepthook(args)

        threading.excepthook = collect_thread_failure
        self.store = SQLiteStore(self.db)
        self._stores.append(self.store)
        self.files = FileService(self.db, self.root)
        self.requirements = RequirementService(self.db)
        req_cfg = AIProviderConfig(
            kind="synthetic", name="本地合成需求通道（非真实 AI）", model_id=None,
            base_url=None, api_key_present=False, adapter_version="rkd-model-provider.v1",
            prompt_version="requirement-understanding.zh-CN.v1",
            schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
            max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
            real_model=False, configuration_errors=[])
        self.requirement_ai = AIRequirementService(
            SQLiteAIRequirementRepository(self.db), self.requirements, config=req_cfg,
            provider_factory=lambda config: build_provider(config))

    def _wait_all_workers(self) -> None:
        """Wait for ALL workers and assert they actually reached idle.

        ``wait_for_idle`` returns silently on timeout, so the private active
        set is checked too — this is lifecycle verification, not a substitute
        for any product entry point.
        """
        self.requirement_ai.wait_for_idle(timeout_seconds=30)
        self.assertFalse(self.requirement_ai._active(), "需求通道 worker 未结束")
        for service in self._services:
            design = service.ai_design_option_service
            if design is not None:
                design.wait_for_idle(timeout_seconds=30)
                self.assertFalse(design._active(), "设计候选 worker 未结束")
            output = service.ai_spatial_output_service
            if output is not None:
                output.wait_for_idle(timeout_seconds=30)

    def tearDown(self):
        problems: list[str] = []
        try:
            self._wait_all_workers()
        except Exception as error:  # noqa: BLE001 - surface as a test failure
            problems.append(f"worker 未安全收尾：{type(error).__name__}: {error}")
        for store in reversed(self._stores):
            try:
                store.close()
            except Exception as error:  # noqa: BLE001
                problems.append(f"关闭 SQLite 失败：{type(error).__name__}: {error}")
        try:
            self.directory.cleanup()
        except Exception as error:  # noqa: BLE001
            problems.append(f"清理临时目录失败：{type(error).__name__}: {error}")
        finally:
            threading.excepthook = self._old_thread_excepthook
        if self._thread_exceptions:
            detail = "\n---\n".join(self._thread_exceptions)
            problems.append(f"后台线程出现未处理异常（{len(self._thread_exceptions)} 条）：\n{detail}")
        if problems:
            self.fail("\n".join(problems))

    # ---------------------------------------------------------------- helpers
    def build_service(self, root: Path | None = None, *, opener,
                      db: Path | None = None) -> ApiService:
        root = root or self.root
        root.mkdir(parents=True, exist_ok=True)
        db = db or self.db
        store = SQLiteStore(db) if db != self.db else self.store
        if db != self.db:
            self._stores.append(store)
        service = ApiService(
            MVPApp(store), FileService(db, root), requirement_service=RequirementService(db),
            ai_requirement_service=self.requirement_ai, runtime_root=root,
            design_option_config=real_config(), design_transport_opener=opener)
        self._services.append(service)
        return service

    def brief(self, service: ApiService, key: str) -> None:
        self.files.seed_ningbo(service, FIXTURE)
        item = service.submit_ai_requirement(
            ORG, PROJECT, "tester",
            {"natural_language": "开放交流，入口在左侧，暖木色"}, key)["item"]
        self.requirement_ai.wait_for_job(ORG, PROJECT, item["job_id"])

    def revisions(self, service: ApiService, set_id: str) -> list[dict]:
        with service.ai_design_option_service.repository.transaction(ORG, PROJECT) as tx:
            return tx.revisions_for_set(set_id)

    def set_row(self, service: ApiService, set_id: str) -> dict:
        return next(row for row in service.get_ai_design_options(ORG, PROJECT)["sets"]
                    if row["set_id"] == set_id)

    def stored_phase(self, set_id: str):
        connection = sqlite3.connect(self.db, timeout=10)
        try:
            return connection.execute(
                "SELECT status, phase FROM ai_design_option_sets WHERE set_id=?",
                (set_id,)).fetchone()
        finally:
            connection.close()

    def stored_revisions(self, set_id: str) -> int:
        connection = sqlite3.connect(self.db, timeout=10)
        try:
            return connection.execute(
                "SELECT COUNT(*) FROM ai_design_option_revisions WHERE set_id=?",
                (set_id,)).fetchone()[0]
        finally:
            connection.close()

    def exchange(self, runtime, marker: str):
        """One real controlled exchange through the runtime's invocation handle."""
        scope = runtime.begin_invocation(PROJECT)
        scope.opener().open(Request(f"http://127.0.0.1:9/stub?marker={marker}", b"{}"))
        return scope

    # ------------------------------------------------------------- R1 (a)
    def test_concurrent_invocations_each_bind_their_own_exchange(self):
        opener = PerCallOpener()
        service = self.build_service(opener=opener)
        self.brief(service, "brief-r1-concurrent")
        runtime = service.controlled_design_runtime

        set_a = service.submit_ai_design_options(
            ORG, PROJECT, "tester", {}, "options-r1-concurrent-a")["item"]["set_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and opener.calls < 1:
            time.sleep(0.001)
        self.assertGreaterEqual(opener.calls, 1, "第一个调用没有发起交换")
        set_b = service.submit_ai_design_options(
            ORG, PROJECT, "tester", {}, "options-r1-concurrent-b")["item"]["set_id"]
        for set_id in (set_a, set_b):
            service.ai_design_option_service.wait_for_set(
                ORG, PROJECT, set_id, timeout_seconds=120)
        service.ai_design_option_service.wait_for_idle(timeout_seconds=30)

        records = {record["run_id"]: record for record in runtime.run_service.export_public()}
        marker_of = {hashlib.sha256(raw).hexdigest(): marker
                     for raw, marker in zip(opener.responses, opener.markers)}
        request_digests = {hashlib.sha256(raw).hexdigest() for raw in opener.requests}
        self.assertEqual(len(opener.responses), 2, "两次并发调用应各发生一次交换")

        seen: dict[str, set] = {}
        for set_id in (set_a, set_b):
            row = self.set_row(service, set_id)
            self.assertEqual(row["status"], "succeeded")
            revisions = self.revisions(service, set_id)
            self.assertEqual(len(revisions), 2)
            markers = set()
            for revision in revisions:
                controlled = revision["validation"]["controlled"]
                record = records[controlled["run_id"]]
                # 1) the run must be signed from THIS invocation's exchange
                markers.add(marker_of[record["response_sha256"]])
                # 2) the request digest must be one actually sent on the wire
                self.assertIn(record["request_sha256"], request_digests)
                # 3) input hash belongs to this persisted candidate set
                self.assertEqual(record["input_hash"], row["input_hash"])
                # 4) candidate digest is this candidate's own immutable source
                source_sha = adapter.sha256_hex(adapter.candidate_from_persisted(
                    controlled["source_candidate"])[0])
                self.assertEqual(record["candidate_sha256"], source_sha)
                self.assertEqual(controlled["provenance"]["sha256"], source_sha)
            self.assertEqual(len(markers), 1,
                             f"候选集 {set_id[-6:]} 内不同候选绑定到了不同交换")
            seen[set_id] = markers

        every = set().union(*seen.values())
        self.assertEqual(len(every), 2,
                         "两个并发调用没有分别绑定各自的交换（观测串线）")
        self.assertEqual(len({record["run_id"] for record in records.values()}), 4)

    # ------------------------------------------------------------- R1 (b)
    def test_observation_scope_isolated_and_missing_fails_closed(self):
        opener = PerCallOpener(pad_first=0)
        service = self.build_service(opener=opener)
        self.brief(service, "brief-r1-scope")
        runtime = service.controlled_design_runtime
        self.assertTrue(hasattr(runtime, "begin_invocation"),
                        "运行时必须提供按 invocation 的观测句柄")

        item = service.submit_ai_design_options(
            ORG, PROJECT, "tester", {}, "options-r1-scope")["item"]
        service.ai_design_option_service.wait_for_set(ORG, PROJECT, item["set_id"],
                                                      timeout_seconds=120)
        revisions = self.revisions(service, item["set_id"])
        model = revisions[0]["validation"]["controlled"]["source_candidate"]

        scope_a = self.exchange(runtime, "a")
        scope_b = self.exchange(runtime, "b")
        self.assertEqual(len(scope_a.observations), 1)
        self.assertEqual(len(scope_b.observations), 1)
        self.assertNotEqual(scope_a.latest().observation_id,
                            scope_b.latest().observation_id)

        # missing observation -> fail closed
        with self.assertRaises(Exception) as missing:
            runtime.register_and_issue(
                project_id=PROJECT, revision_id="rev-empty-000001",
                candidate_model=model, observation=None,
                scope=runtime.begin_invocation(PROJECT), config=real_config(),
                input_hash="h" * 64)
        self.assertEqual(getattr(missing.exception, "code", ""), "CONTROLLED_EXCHANGE_MISSING")

        # another invocation's observation -> fail closed
        with self.assertRaises(Exception) as foreign:
            runtime.register_and_issue(
                project_id=PROJECT, revision_id="rev-foreign-00001",
                candidate_model=model, observation=scope_b.latest(), scope=scope_a,
                config=real_config(), input_hash="h" * 64)
        self.assertEqual(getattr(foreign.exception, "code", ""), "OBSERVATION_NOT_FROM_INVOCATION")

        # own observation -> accepted, bound to exactly this exchange
        record, provenance = runtime.register_and_issue(
            project_id=PROJECT, revision_id="rev-own-0000001", candidate_model=model,
            observation=scope_a.latest(), scope=scope_a, config=real_config(),
            input_hash="h" * 64)
        self.assertEqual(record["observation_id"], scope_a.latest().observation_id)
        self.assertEqual(record["response_sha256"], scope_a.latest().response_sha256)
        self.assertEqual(provenance["design_origin"]["run_refs"], [record["run_id"]])

    # ------------------------------------------------------- R1 scope REQUIRED
    def test_issuance_rejects_omitted_or_null_scope(self):
        """Both issuance APIs must require scope; observation alone is not enough."""
        from rkd_mvp.controlled_run_ledger import RunLedgerError

        service = self.build_service(opener=PerCallOpener(pad_first=0))
        self.brief(service, "brief-r1-scope-required")
        item = service.submit_ai_design_options(
            ORG, PROJECT, "tester", {}, "options-r1-scope-required")["item"]
        service.ai_design_option_service.wait_for_set(ORG, PROJECT, item["set_id"],
                                                      timeout_seconds=120)
        model = self.revisions(service, item["set_id"])[0]["validation"]["controlled"]["source_candidate"]
        runtime = service.controlled_design_runtime
        scope = self.exchange(runtime, "scope-required")
        source_sha = adapter.sha256_hex(adapter.candidate_from_persisted(model)[0])

        # 1) runtime API: omitting scope is rejected by the call boundary;
        #    explicit None is rejected with a stable ledger code.
        runtime_kwargs = dict(
            project_id=PROJECT, revision_id="rev-no-scope-00001", candidate_model=model,
            observation=scope.latest(), config=real_config(), input_hash="h" * 64)
        registered_before = [key for key in runtime.run_service._revisions
                             if key[0] == PROJECT]
        with self.assertRaises(TypeError):
            runtime.register_and_issue(**runtime_kwargs)
        with self.assertRaises(RunLedgerError) as missing:
            runtime.register_and_issue(**runtime_kwargs, scope=None)
        self.assertEqual(missing.exception.code, "OBSERVATION_SCOPE_REQUIRED")
        self.assertEqual([key for key in runtime.run_service._revisions if key[0] == PROJECT],
                         registered_before, "省略 scope 的调用不得留下任何登记")

        # 2) ledger API: same rule even for a genuine observation of this ledger.
        ledger_kwargs = dict(
            observation=scope.latest(), project_id=PROJECT, candidate_sha256=source_sha,
            input_hash="h" * 64, output_sha256=hashlib.sha256(canon(model)).hexdigest(),
            model="stub-model", prompt_version="pv", site_snapshot_sha256="s" * 64,
            basemap_files_sha256="b" * 64)
        with self.assertRaises(TypeError):
            runtime.run_service.issue(**ledger_kwargs)
        with self.assertRaises(RunLedgerError) as null_scope:
            runtime.run_service.issue(**ledger_kwargs, scope=None)
        self.assertEqual(null_scope.exception.code, "OBSERVATION_SCOPE_REQUIRED")

        # 3) a scope from another service instance is not accepted either.
        other_runtime = self.build_service(
            self.root / "other", opener=PerCallOpener(pad_first=0)
        ).controlled_design_runtime
        other_scope = self.exchange(other_runtime, "other-service")
        with self.assertRaises(RunLedgerError) as foreign_scope:
            runtime.run_service.issue(**ledger_kwargs, scope=other_scope)
        self.assertEqual(foreign_scope.exception.code, "OBSERVATION_SCOPE_INVALID")

        # 4) the real product path still issues with a scope from its own runtime.
        record, _provenance = runtime.register_and_issue(
            **{**runtime_kwargs, "revision_id": "rev-with-scope-0001"}, scope=scope)
        self.assertEqual(record["observation_id"], scope.latest().observation_id)

    # ---------------------------------------------------------------- R2
    def test_phantom_parent_revision_rejected(self):
        healthy = PerCallOpener(pad_first=0)
        service = self.build_service(opener=healthy)
        self.brief(service, "brief-r2-phantom")
        ok_set = service.submit_ai_design_options(
            ORG, PROJECT, "tester", {}, "options-r2-healthy")["item"]["set_id"]
        service.ai_design_option_service.wait_for_set(ORG, PROJECT, ok_set,
                                                      timeout_seconds=120)
        ok_rows = self.revisions(service, ok_set)
        self.assertEqual(len(ok_rows), 2)
        model = ok_rows[0]["validation"]["controlled"]["source_candidate"]

        # second composition root over the same store discards the running set
        # after the controlled finalize (public API only)
        blocking = BlockingOpener()
        self.addCleanup(blocking.release.set)  # never leave a worker parked on failure
        owner = self.build_service(self.root / "owner", opener=blocking)
        shadow = self.build_service(self.root / "shadow", opener=BlockingOpener())
        owner_runtime = owner.controlled_design_runtime

        bad_set = owner.submit_ai_design_options(
            ORG, PROJECT, "tester", {}, "options-r2-phantom")["item"]["set_id"]
        self.assertTrue(blocking.entered.wait(timeout=20), "阻塞桩没有被调用")
        blocking.release.set()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            row = self.stored_phase(bad_set)
            if row and row[1] == "outputs":
                break
        shadow.get_ai_design_options(ORG, PROJECT)   # reclaim -> WORKER_RESTARTED
        for _ in range(400):
            row = self.stored_phase(bad_set)
            if row and row[0] in {"failed", "cancelled", "succeeded"}:
                break
            time.sleep(0.01)
        # Explicitly wait for EVERY worker on the owner/shadow services and
        # verify the terminal state before asserting or tearing down.  A fixed
        # sleep here used to let tearDown delete the tree under a live worker.
        for svc in (owner, shadow):
            svc.ai_design_option_service.wait_for_idle(timeout_seconds=30)
            self.assertFalse(svc.ai_design_option_service._active(),
                             f"{svc} 的设计候选 worker 未结束")
        self.assertEqual((self.stored_phase(bad_set) or [None])[0], "failed",
                         "被丢弃的候选集应终态 failed")

        self.assertEqual(self.stored_revisions(bad_set), 0,
                         "被丢弃的候选集不应写业务修订")
        self.assertNotEqual((self.stored_phase(bad_set) or [None])[0], "succeeded")
        registered = [key for key in owner_runtime.run_service._revisions
                      if key[0] == PROJECT]
        self.assertEqual(
            registered, [],
            "业务候选没有提交，账本不得登记可当父链的修订（幽灵父修订）")

        # whatever id the run record targeted must not be usable as a parent
        target = None
        for record in owner_runtime.run_service.export_public():
            revision_id = (record.get("details") or {}).get("revision_id")
            if revision_id:
                target = revision_id
                break
        self.assertIsNotNone(target, "运行记录必须记录本次尝试的修订号，便于追责与父链拒绝")

        scope = self.exchange(owner_runtime, "parent")
        with self.assertRaises(Exception) as rejected:
            owner_runtime.register_and_issue(
                project_id=PROJECT, revision_id="rev-child-000001",
                candidate_model=model, observation=scope.latest(), scope=scope,
                config=real_config(), input_hash="h" * 64,
                parent_revision_id=target)
        self.assertIn(getattr(rejected.exception, "code", ""),
                      {"PARENT_UNREGISTERED", "PARENT_NOT_COMMITTED"})

    def test_registration_happens_only_after_commit(self):
        opener = PerCallOpener(pad_first=0)
        service = self.build_service(opener=opener)
        self.brief(service, "brief-r2-commit")
        runtime = service.controlled_design_runtime
        self.assertEqual([key for key in runtime.run_service._revisions
                          if key[0] == PROJECT], [],
                         "新运行时不应有历史登记")

        set_id = service.submit_ai_design_options(
            ORG, PROJECT, "tester", {}, "options-r2-commit")["item"]["set_id"]
        service.ai_design_option_service.wait_for_set(ORG, PROJECT, set_id,
                                                      timeout_seconds=120)
        revisions = self.revisions(service, set_id)
        self.assertEqual(len(revisions), 2)

        registered = {(key[1], value) for key, value in runtime.run_service._revisions.items()
                      if key[0] == PROJECT}
        self.assertEqual({key for key, _ in registered},
                         {revision["option_revision_id"] for revision in revisions},
                         "已提交的候选必须全部登记")
        for revision in revisions:
            controlled = revision["validation"]["controlled"]
            source_sha = adapter.sha256_hex(adapter.candidate_from_persisted(
                controlled["source_candidate"])[0])
            self.assertIn((revision["option_revision_id"], source_sha), registered,
                          "登记摘要必须是该候选不可变来源的摘要")


if __name__ == "__main__":
    unittest.main()
