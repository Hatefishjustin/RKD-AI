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

import copy
from pathlib import Path
from typing import Any

from . import realmodel_spatial_adapter as A
from . import site_snapshot as SS
from .admission import admit_document
from .controlled_run_ledger import ControlledRunService

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
                 isolated_test: bool = False) -> None:
        self.run_service = ControlledRunService(
            store_dir, opener=opener, transport="local_protocol_stub",
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

    def verifier(self) -> Any:
        return self.run_service.verifier()

    # -- controlled run issuance --------------------------------------------
    def register_and_issue(self, *, project_id: str, revision_id: str,
                           candidate_model: dict, observation: Any, config: Any,
                           input_hash: str,
                           parent_revision_id: str | None = None) -> tuple[dict, dict]:
        """Issue a run bound to the immutable candidate + observed exchange."""
        cand, _ = A.candidate_from_persisted(candidate_model)
        candidate_sha = A.sha256_hex(cand)
        self.run_service.register_revision(
            project_id=project_id, revision_id=revision_id,
            candidate_sha256=candidate_sha)
        record = self.run_service.issue(
            observation=observation, project_id=project_id,
            candidate_sha256=candidate_sha, input_hash=input_hash,
            output_sha256=A.sha256_hex(candidate_model),
            model=str(config.model_id or "stub-model"),
            prompt_version=str(config.prompt_version),
            site_snapshot_sha256=self.snapshot["sha256"],
            basemap_files_sha256=self.snapshot["basemap_files_sha256"],
            parent_revision_id=parent_revision_id,
            details={"transport_note": "受控传输实际交换；注入桩恒为模拟，不是真实模型"})
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
            "provider_kind": "local_protocol_stub",
            "prompt_version": str(config.prompt_version),
            "model_id": str(config.model_id or "stub-model"),
            "site_snapshot_sha256": self.snapshot["sha256"],
            "basemap_files_sha256": self.snapshot["basemap_files_sha256"],
            "design_origin": {
                "kind": "fixture", "declared_by": "controlled-design-runtime",
                "declaration": "本地协议桩模拟；来源为 fixture，不冒充真实模型",
                "run_refs": [record["run_id"]]},
        }
        return record, provenance

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

    @staticmethod
    def fresh_observation(observations: list[Any]) -> Any | None:
        return observations[-1] if observations else None
