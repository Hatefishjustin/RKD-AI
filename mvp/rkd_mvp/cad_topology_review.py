from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


REVIEW_ROUTES = {
    "architecture.detail": ("supporting-evidence-only", "detail-is-not-a-quantity-object"),
    "architecture.opening.door": ("needs-wall-opening-pairing", "door-must-pair-with-wall-opening"),
    "architecture.wall": ("needs-wall-boundary-pairing", "wall-lines-require-boundary-or-centerline-model"),
    "interior.ceiling": ("needs-boundary-polygonization", "ceiling-network-requires-closed-regions"),
    "interior.floor.finish-line": ("needs-boundary-polygonization", "floor-network-requires-closed-regions"),
    "interior.furniture.fixed": ("needs-component-decomposition", "furniture-network-requires-component-splitting"),
    "interior.furniture.loose": ("needs-component-decomposition", "furniture-network-requires-component-splitting"),
}

SPLIT_THRESHOLDS = {
    "architecture.detail": 4,
    "architecture.opening.door": 4,
    "architecture.wall": 20,
    "interior.ceiling": 10,
    "interior.floor.finish-line": 10,
    "interior.furniture.fixed": 12,
    "interior.furniture.loose": 8,
}


class CadTopologyReviewBuilder:
    """Creates conservative, category-specific review work from geometry groups."""

    def build(
        self,
        plan_candidates: Mapping[str, Any],
        object_groups: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._validate_inputs(plan_candidates, object_groups)
        candidate_by_id = {
            item["candidate_id"]: item for item in plan_candidates["candidates"]
        }
        items: list[dict[str, Any]] = []
        status_counts: Counter[str] = Counter()
        reason_counts: Counter[str] = Counter()
        category_counts: Counter[str] = Counter()
        oversized_counts: Counter[str] = Counter()

        for group in object_groups["groups"]:
            category = group["category"]
            members = [candidate_by_id[item] for item in group["candidate_ids"]]
            if len(members) != group["candidate_count"]:
                raise ValueError("Geometry group references missing plan candidates.")
            status, reason = REVIEW_ROUTES.get(
                category,
                ("needs-professional-rule", "category-has-no-topology-rule"),
            )
            threshold = SPLIT_THRESHOLDS.get(category, 1)
            oversized = group["candidate_count"] > threshold
            if oversized:
                oversized_counts[category] += 1
            closed_count = sum(item.get("source_geometry_closed") is True for item in members)
            unknown_closed_count = sum(item.get("source_geometry_closed") is None for item in members)
            block_count = sum(item.get("requires_block_expansion") is True for item in members)
            size_x = float(group["bounds"]["maximum"][0]) - float(group["bounds"]["minimum"][0])
            size_y = float(group["bounds"]["maximum"][1]) - float(group["bounds"]["minimum"][1])
            review_reasons = [reason]
            if oversized:
                review_reasons.append("connected-network-exceeds-split-threshold")
            if category in {"interior.ceiling", "interior.floor.finish-line"} and closed_count == 0:
                review_reasons.append("no-closed-source-primitive")
            if category == "architecture.opening.door" and block_count == 0:
                review_reasons.append("door-has-no-block-instance")
            for code in review_reasons:
                reason_counts[code] += 1
            status_counts[status] += 1
            category_counts[category] += 1
            items.append({
                "group_id": group["group_id"],
                "category": category,
                "review_status": status,
                "review_reasons": review_reasons,
                "candidate_count": group["candidate_count"],
                "closed_source_candidate_count": closed_count,
                "unknown_closure_candidate_count": unknown_closed_count,
                "block_instance_candidate_count": block_count,
                "bounds_size_mm": {"x": round(size_x, 6), "y": round(size_y, 6)},
                "requires_network_split": oversized,
                "requires_secondary_cad_validation": True,
                "domain_object_status": "not-created",
                "quantity_status": "not-ready",
                "user_confirmation_required_now": False,
            })

        return {
            "contract_version": "1.0",
            "source_asset_id": plan_candidates["source_asset_id"],
            "source_sha256": plan_candidates["source_sha256"],
            "plan_profile_id": plan_candidates["profile_id"],
            "status": "topology-review-queue-created",
            "summary": {
                "input_geometry_group_count": len(object_groups["groups"]),
                "review_item_count": len(items),
                "review_status_counts": dict(sorted(status_counts.items())),
                "review_reason_counts": dict(sorted(reason_counts.items())),
                "category_review_counts": dict(sorted(category_counts.items())),
                "oversized_network_counts": dict(sorted(oversized_counts.items())),
                "created_domain_object_count": 0,
                "quantity_ready_count": 0,
                "user_confirmation_required_now": False,
            },
            "items": items,
            "warnings": [
                {
                    "code": "TOPOLOGY_REVIEW_IS_NOT_OBJECT_APPROVAL",
                    "message": "The queue routes each group to a professional validation rule and does not create approved domain objects.",
                },
                {
                    "code": "SECONDARY_CAD_ENGINE_REQUIRED",
                    "message": "All groups remain blocked from quantity production until a second CAD engine or original CAD software validates the geometry sample.",
                },
            ],
        }

    @staticmethod
    def _validate_inputs(
        plan_candidates: Mapping[str, Any],
        object_groups: Mapping[str, Any],
    ) -> None:
        if plan_candidates.get("status") != "candidate-extraction-complete":
            raise ValueError("Topology review requires completed plan candidates.")
        if object_groups.get("status") != "geometry-grouping-complete":
            raise ValueError("Topology review requires completed geometry groups.")
        if object_groups.get("source_sha256") != plan_candidates.get("source_sha256"):
            raise ValueError("Geometry groups and plan candidates source hashes differ.")
