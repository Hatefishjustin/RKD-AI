"""Composition root for the W3 controlled real-model design chain (R1).

This module is PRODUCTION code, not a verification-script shim.  It composes
the pieces that each already had a single responsibility into the actual chain
the product requires:

    confirmed site snapshot -> provider (through controlled transport)
      -> real SQLite repository (immutable persisted candidate)
      -> controlled run service (observes the ACTUAL exchange bytes)
      -> controlled spatial adaptation (site gate + projection rebuild)
      -> trusted admission (service-context org/project + immutable digest)
      -> adoption gate (reads the persisted admission)

The runtime is injected into ``AIDesignOptionService``; nothing here mutates a
contract, disables the admission gate, or fabricates a real source.  With an
injected protocol-stub opener every run record is ``simulated=True`` and the
design origin stays ``fixture`` — no paid external call, no fake real model.

Trust boundary (R2): the transport opener is bound at composition time.  A
caller of the service can neither assert transport/endpoint/bytes nor promote a
source to ``real_model``.  In-process attacker with arbitrary execution is OUT
of scope, as stated in the review packet.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import realmodel_spatial_adapter as A
from . import site_snapshot as SS
from .admission import admit_document
from .controlled_run_ledger import ControlledRunService, RunLedgerError
from .ai_design_option_provider import DesignOptionConfig, load_design_option_config


class ControlledRuntimeSetupError(Exception):
    """Startup configuration cannot support a controlled real-model chain."""

    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(f"{code}: {message}")

DEFAULT_BASEMAP = (Path(__file__).resolve().parents[2]
                   / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap")
DEFAULT_ENTRANCE = [0.0, 10.3]
DEFAULT_ENTRANCE_REASON = ("底图仅推断西门厅；概念暂用点位，现场复核后替换")


class ControlledDesignRuntime:
    """Owns the controlled run service and the single canonical site snapshot."""

    def __init__(self, *, store_dir: str | Path, opener: Any,
                 basemap_dir: str | Path | None = None,
                 entrance_point_m: list[float] | None = None,
                 entrance_reason: str = DEFAULT_ENTRANCE_REASON,
                 isolated_test: bool = False,
                 transport: str = "local_protocol_stub") -> None:
        self.run_service = ControlledRunService(
            store_dir, opener=opener, transport=transport,
            isolated_test=isolated_test)
        self.basemap_dir = Path(basemap_dir) if basemap_dir else DEFAULT_BASEMAP
        facts = A._load_basemap_facts(self.basemap_dir)
        self.snapshot = SS.build_snapshot(
            facts=facts,
            entrance_point_m=list(entrance_point_m) if entrance_point_m else list(DEFAULT_ENTRANCE),
            entrance_reason=entrance_reason)
        SS.verify_snapshot_shape(self.snapshot)

    # -- site facts (one canonical snapshot, two named digests) --------------
    def provider_site(self) -> dict:
        return SS.provider_site(self.snapshot)

    def adapter_site(self) -> dict:
        return SS.adapter_site(self.snapshot)

    def site_for_provider(self, project_id: str) -> dict:
        """Site with the canonical snapshot for the provider request."""
        return self.provider_site()

    def bound_opener(self, project_id: str) -> Any:
        return self.run_service.transport().bind(project_id)

    def begin_invocation(self, project_id: str) -> Any:
        """One provider invocation -> one observation scope (R1).

        The provider may only use ``scope.opener()`` and the candidate may only
        be signed from ``scope.latest()``, so concurrent invocations on the same
        project cannot bind each other's exchange.
        """
        return self.run_service.begin_invocation(str(project_id))

    def verifier(self) -> Any:
        return self.run_service.verifier()

    # -- controlled run issuance --------------------------------------------
    def register_and_issue(self, *, project_id: str, revision_id: str,
                           candidate_model: dict, observation: Any, config: Any,
                           input_hash: str, scope: Any = None,
                           parent_revision_id: str | None = None) -> tuple[dict, dict]:
        """Issue a run bound to the immutable candidate + its OWN invocation's exchange.

        The revision is deliberately NOT registered here (R2): a revision may only
        become a parent after the business candidate is committed, which is what
        :meth:`commit_revision` records.
        """
        cand, _ = A.candidate_from_persisted(candidate_model)
        candidate_sha = A.sha256_hex(cand)
        if observation is None:
            raise RunLedgerError("CONTROLLED_EXCHANGE_MISSING",
                                 "受控传输没有观测到本次调用的实际模型交换，不能签发运行记录")
        record = self.run_service.issue(
            observation=observation, project_id=project_id,
            candidate_sha256=candidate_sha, input_hash=input_hash,
            output_sha256=A.sha256_hex(candidate_model),
            model=str(config.model_id or "stub-model"),
            prompt_version=str(config.prompt_version),
            site_snapshot_sha256=self.snapshot["sha256"],
            basemap_files_sha256=self.snapshot["basemap_files_sha256"],
            parent_revision_id=parent_revision_id,
            details={"revision_id": revision_id,
                     "transport_note": "受控传输实际交换；注入桩恒为模拟，不是真实模型"},
            scope=scope)
        # Origin declaration follows the SIGNED run record, never a hard-coded
        # claim: a stub exchange stays fixture/simulated, a verified live run
        # may be declared real_model by a separate authorized path.
        declared_kind = "real_model" if (record.get("kind") == "real_model_run"
                                        and record.get("simulated") is False) else "fixture"
        declaration = ("受控服务观测真实 HTTP 交换并签发；按运行记录声明真实来源"
                       if declared_kind == "real_model" else
                       "本地协议桩/未核验传输：来源为 fixture，不冒充真实模型")
        provenance = {
            "sha256": candidate_sha,
            "artifact_id": revision_id,
            "set_id": candidate_model.get("set_id"),
            "option_id": candidate_model.get("option_id"),
            "revision_no": candidate_model.get("revision_no"),
            "parent_revision_id": parent_revision_id,
            "actor_id": candidate_model.get("actor_id"),
            "model_site_boundary_m": [self.snapshot["width_m"], self.snapshot["length_m"]],
            "project_id": project_id,
            "provider_kind": str(record.get("transport") or "local_protocol_stub"),
            "prompt_version": str(config.prompt_version),
            "model_id": str(config.model_id or "stub-model"),
            "site_snapshot_sha256": self.snapshot["sha256"],
            "basemap_files_sha256": self.snapshot["basemap_files_sha256"],
            "design_origin": {
                "kind": declared_kind, "declared_by": "controlled-design-runtime",
                "declaration": declaration,
                "run_refs": [record["run_id"]]},
        }
        return record, provenance

    # -- post-commit parent-chain registration (R2) --------------------------
    def commit_revision(self, *, project_id: str, revision_id: str,
                        candidate_sha256: str) -> dict:
        """Register a revision as a valid parent ONLY after the business row exists.

        Called by the service after its repository transaction committed.  A
        candidate that never persisted therefore never becomes a parent, so the
        ledger cannot hold a phantom revision (R2).
        """
        if not candidate_sha256:
            raise RunLedgerError("REVISION_REGISTRATION_INVALID",
                                 "登记父修订必须带该候选不可变来源摘要")
        return self.run_service.register_revision(
            project_id=project_id, revision_id=revision_id,
            candidate_sha256=candidate_sha256)

    # -- controlled adaptation ----------------------------------------------
    def adapt(self, persisted_candidate: dict, *, provenance: dict,
              created_at: str) -> tuple[dict, dict]:
        return A.adapt_persisted_candidate(
            persisted_candidate, site=self.adapter_site(),
            basemap_dir=self.basemap_dir, provenance=provenance,
            created_at=created_at, run_verifier=self.verifier())

    def admit(self, adapted_document: dict, *, organization_id: str,
              project_id: str, source_candidate: dict,
              provenance: dict) -> dict:
        return admit_document(
            adapted_document, site=self.adapter_site(),
            basemap_dir=self.basemap_dir, run_verifier=self.verifier(),
            organization_id=organization_id, project_id=project_id,
            source_candidate=source_candidate, provenance=provenance)


def build_controlled_runtime(*, runtime_root: str | Path,
                             config: DesignOptionConfig | None = None,
                             opener: Any | None = None,
                             basemap_dir: str | Path | None = None,
                             environ: dict[str, str] | None = None) -> ControlledDesignRuntime:
    """Create the controlled runtime from the REAL application configuration.

    Called by the application composition roots (``ApiService`` /
    ``PostgresApiService``) when the configured design provider is a real model.
    It never fabricates a real source:

    * a real-model config with missing base_url/model/key FAILS CLOSED here;
    * the transport opener is injected by the composition root (an injected
      opener is a local stub => every run is simulated); with no opener the
      live HTTP opener is used and only a non-loopback endpoint can be real;
    * the basemap comes from the confirmed v2 files, never from the request.

    ``environ`` is only for tests; production reads ``os.environ``.  The API key
    is never copied into the runtime, a file or a log — it stays in the process
    environment and is read by the provider at call time.
    """
    env = dict(os.environ if environ is None else environ)
    cfg = config or load_design_option_config(env)
    if cfg.kind != "openai_compatible":
        raise ControlledRuntimeSetupError(
            "REAL_MODEL_REQUIRED",
            "受控运行时只服务真实模型配置（openai_compatible）；合成通道保持原有非 AI 路径")
    if cfg.configuration_errors:
        raise ControlledRuntimeSetupError(
            "DESIGN_CONFIG_INCOMPLETE",
            "真实模型配置不完整，拒绝以不完整配置启动受控链：" + "；".join(cfg.configuration_errors))
    if not cfg.api_key_present and not (env.get("RKD_AI_API_KEY") or "").strip():
        raise ControlledRuntimeSetupError(
            "API_KEY_REQUIRED",
            "真实模型运行必须提供会话环境变量 RKD_AI_API_KEY；不写入文件/日志/仓储")
    from .controlled_run_ledger import build_live_opener
    transport = "local_protocol_stub" if opener is not None else "live_http"
    store_dir = Path(runtime_root) / "controlled-runs"
    return ControlledDesignRuntime(
        store_dir=store_dir, opener=opener if opener is not None else build_live_opener(),
        transport=transport, basemap_dir=basemap_dir, isolated_test=False)
