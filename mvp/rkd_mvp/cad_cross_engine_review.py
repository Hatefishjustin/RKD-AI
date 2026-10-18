from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


class CadCrossEngineReviewBuilder:
    """Matches DXF and DWG candidates by preserved CAD handle and bounded geometry."""

    def build(
        self,
        dxf_review: Mapping[str, Any],
        dwg_candidates: Mapping[str, Any],
        direct_tolerance_mm: float = 0.01,
        arc_tolerance_mm: float = 0.5,
    ) -> dict[str, Any]:
        if dxf_review.get("status") != "geometry-review-created":
            raise ValueError("Cross-engine review requires a completed DXF geometry review.")
        if dwg_candidates.get("status") != "candidate-extraction-complete":
            raise ValueError("Cross-engine review requires completed DWG candidates.")
        if direct_tolerance_mm <= 0 or arc_tolerance_mm <= 0:
            raise ValueError("Geometry tolerances must be positive.")

        dxf_by_handle = {int(item["entity_handle"]): item for item in dxf_review["evidence_sample"]}
        dwg_by_handle = {int(item["source_entity_handle"]): item for item in dwg_candidates["candidates"]}
        common = sorted(set(dxf_by_handle) & set(dwg_by_handle))
        dxf_only = sorted(set(dxf_by_handle) - set(dwg_by_handle))
        dwg_only = sorted(set(dwg_by_handle) - set(dxf_by_handle))
        matches: list[dict[str, Any]] = []
        mismatch_reasons: Counter[str] = Counter()
        match_statuses: Counter[str] = Counter()

        for handle in common:
            dxf = dxf_by_handle[handle]
            dwg = dwg_by_handle[handle]
            reasons: list[str] = []
            if dxf["category"] != dwg["category"]:
                reasons.append("category-difference")
            if dxf["layer"] != dwg["source_layer"]:
                reasons.append("layer-difference")
            if dxf["entity_type"] != dwg["source_entity_type"]:
                reasons.append("entity-type-difference")
            if dxf["entity_type"] == "INSERT":
                dxf_bounds = dxf.get("block_expansion", {}).get("expanded_bounds")
                comparison_mode = "expanded-block-bounds"
                tolerance = direct_tolerance_mm
            else:
                dxf_bounds = dxf["bounds"]
                comparison_mode = "direct-entity-bounds"
                tolerance = arc_tolerance_mm if dxf["entity_type"] == "ARC" else direct_tolerance_mm
            delta = self._bounds_delta(dxf_bounds, dwg["bounds"])
            if delta is None:
                reasons.append("geometry-not-comparable")
            elif delta > tolerance:
                reasons.append("geometry-outside-tolerance")
            for reason in reasons:
                mismatch_reasons[reason] += 1
            status = "matched" if not reasons else "review-required"
            match_statuses[status] += 1
            matches.append({
                "entity_handle": handle,
                "category": dxf["category"],
                "layer": dxf["layer"],
                "entity_type": dxf["entity_type"],
                "comparison_mode": comparison_mode,
                "tolerance_mm": tolerance,
                "maximum_bounds_delta_mm": round(delta, 9) if delta is not None else None,
                "status": status,
                "review_reasons": reasons,
            })

        dxf_only_categories = Counter(dxf_by_handle[handle]["category"] for handle in dxf_only)
        dxf_only_types = Counter(dxf_by_handle[handle]["entity_type"] for handle in dxf_only)
        dwg_only_categories = Counter(dwg_by_handle[handle]["category"] for handle in dwg_only)
        dwg_only_types = Counter(dwg_by_handle[handle]["source_entity_type"] for handle in dwg_only)
        professional_categories = {
            "architecture.detail", "architecture.opening.door", "architecture.wall",
            "interior.ceiling", "interior.floor.finish-line", "interior.furniture.fixed",
            "interior.furniture.loose", "mep.electrical.lighting-fixture",
            "mep.electrical.outlet", "mep.electrical.switch",
        }
        matched_professional = sum(
            item["status"] == "matched" and item["category"] in professional_categories
            for item in matches
        )
        return {
            "contract_version": "1.0",
            "dxf_source_asset_id": dxf_review["source_asset_id"],
            "dxf_source_sha256": dxf_review["source_sha256"],
            "dwg_source_asset_id": dwg_candidates["source_asset_id"],
            "dwg_source_sha256": dwg_candidates["source_sha256"],
            "plan_profile_id": dwg_candidates["profile_id"],
            "status": "cross-engine-review-created",
            "policy": {
                "identity_key": "preserved-cad-entity-handle",
                "direct_bounds_tolerance_mm": direct_tolerance_mm,
                "arc_bounds_tolerance_mm": arc_tolerance_mm,
                "block_comparison": "expanded-block-bounds",
            },
            "summary": {
                "dxf_candidate_count": len(dxf_by_handle),
                "dwg_candidate_count": len(dwg_by_handle),
                "common_handle_count": len(common),
                "matched_handle_count": match_statuses["matched"],
                "review_required_handle_count": match_statuses["review-required"],
                "matched_professional_candidate_count": matched_professional,
                "dxf_only_count": len(dxf_only),
                "dwg_only_count": len(dwg_only),
                "mismatch_reason_counts": dict(sorted(mismatch_reasons.items())),
                "created_domain_object_count": 0,
                "quantity_ready_count": 0,
                "promotion_status": "not-approved",
            },
            "matched_candidates": matches,
            "dxf_only": {
                "handles": dxf_only,
                "category_counts": dict(sorted(dxf_only_categories.items())),
                "entity_type_counts": dict(sorted(dxf_only_types.items())),
            },
            "dwg_only": {
                "handles": dwg_only,
                "category_counts": dict(sorted(dwg_only_categories.items())),
                "entity_type_counts": dict(sorted(dwg_only_types.items())),
            },
            "warnings": [
                {
                    "code": "HANDLE_MATCH_IS_NOT_PROFESSIONAL_APPROVAL",
                    "message": "Preserved handles and matching bounds strongly corroborate geometry but do not establish wall, room, quantity, or construction approval.",
                },
                {
                    "code": "UNMATCHED_ENTITIES_REQUIRE_TYPE_AWARE_REVIEW",
                    "message": "DXF-only and DWG-only evidence includes intentionally excluded annotations, hatches, dimensions, leaders, and reference layers; compare by entity role before classifying data loss.",
                },
            ],
        }

    @staticmethod
    def _bounds_delta(first: Any, second: Any) -> float | None:
        if not isinstance(first, Mapping) or not isinstance(second, Mapping):
            return None
        try:
            return max(
                abs(float(first[key][index]) - float(second[key][index]))
                for key in ("minimum", "maximum")
                for index in range(2)
            )
        except (KeyError, IndexError, TypeError, ValueError):
            return None
