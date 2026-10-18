from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import Any, Mapping, Sequence


class CadObjectGroupBuilder:
    """Groups connected CAD candidates without promoting them to final domain objects."""

    def build(
        self,
        plan_candidates: Mapping[str, Any],
        endpoint_tolerance_mm: float = 2.0,
    ) -> dict[str, Any]:
        if plan_candidates.get("status") != "candidate-extraction-complete":
            raise ValueError("Object grouping requires completed plan candidates.")
        if endpoint_tolerance_mm <= 0:
            raise ValueError("Endpoint tolerance must be positive.")
        candidates = [
            item for item in plan_candidates["candidates"]
            if item.get("eligible_for_current_scope") is True
        ]
        by_category: dict[str, list[Mapping[str, Any]]] = {}
        for candidate in candidates:
            if len(candidate.get("geometry_points", [])) != candidate.get("point_count"):
                raise ValueError("Candidate point count does not match geometry_points.")
            by_category.setdefault(candidate["category"], []).append(candidate)

        groups: list[dict[str, Any]] = []
        category_summary: list[dict[str, Any]] = []
        for category, category_candidates in sorted(by_category.items()):
            partitions = self._connected_partitions(category_candidates, endpoint_tolerance_mm)
            category_groups = []
            for partition in partitions:
                members = [category_candidates[index] for index in partition]
                group = self._make_group(
                    plan_candidates["source_sha256"], category, members
                )
                groups.append(group)
                category_groups.append(group)
            category_summary.append({
                "category": category,
                "candidate_count": len(category_candidates),
                "group_count": len(category_groups),
                "singleton_group_count": sum(item["candidate_count"] == 1 for item in category_groups),
                "largest_group_candidate_count": max(item["candidate_count"] for item in category_groups),
            })

        return {
            "contract_version": "1.0",
            "source_asset_id": plan_candidates["source_asset_id"],
            "source_sha256": plan_candidates["source_sha256"],
            "plan_profile_id": plan_candidates["profile_id"],
            "status": "geometry-grouping-complete",
            "grouping_policy": {
                "policy_id": "connected-endpoints-or-intersections-v1",
                "endpoint_tolerance_mm": endpoint_tolerance_mm,
                "block_instances_are_isolated": True,
                "cross_category_merging": False,
            },
            "summary": {
                "input_current_scope_candidate_count": len(candidates),
                "geometry_group_count": len(groups),
                "category_count": len(category_summary),
                "final_domain_object_count": 0,
                "quantity_ready_group_count": 0,
                "user_confirmation_required_now": False,
            },
            "category_summary": category_summary,
            "groups": groups,
            "warnings": [
                {
                    "code": "GROUPS_ARE_NOT_FINAL_OBJECTS",
                    "message": "Connected geometry groups require category-specific topology validation before becoming walls, doors, furniture, spaces, or quantities.",
                },
                {
                    "code": "SECONDARY_CAD_VALIDATION_REQUIRED",
                    "message": "Grouping is based on the first CAD parser result and is not construction verified.",
                },
            ],
        }

    def _connected_partitions(
        self,
        candidates: Sequence[Mapping[str, Any]],
        tolerance: float,
    ) -> list[list[int]]:
        parent = list(range(len(candidates)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(first: int, second: int) -> None:
            first_root = find(first)
            second_root = find(second)
            if first_root != second_root:
                parent[second_root] = first_root

        for first_index, first in enumerate(candidates):
            if first.get("requires_block_expansion"):
                continue
            for second_index in range(first_index + 1, len(candidates)):
                second = candidates[second_index]
                if second.get("requires_block_expansion"):
                    continue
                if self._geometry_touches(first, second, tolerance):
                    union(first_index, second_index)

        partitions: dict[int, list[int]] = {}
        for index in range(len(candidates)):
            partitions.setdefault(find(index), []).append(index)
        return sorted(partitions.values(), key=lambda item: min(item))

    @classmethod
    def _geometry_touches(
        cls,
        first: Mapping[str, Any],
        second: Mapping[str, Any],
        tolerance: float,
    ) -> bool:
        if cls._bounds_distance(first["bounds"], second["bounds"]) > tolerance:
            return False
        first_points = first["geometry_points"]
        second_points = second["geometry_points"]
        tolerance_squared = tolerance * tolerance
        if any(
            (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2 <= tolerance_squared
            for left in first_points
            for right in second_points
        ):
            return True
        return any(
            cls._segments_intersect(a, b, c, d, tolerance)
            for a, b in zip(first_points, first_points[1:])
            for c, d in zip(second_points, second_points[1:])
        )

    @staticmethod
    def _bounds_distance(first: Mapping[str, Any], second: Mapping[str, Any]) -> float:
        dx = max(
            float(first["minimum"][0]) - float(second["maximum"][0]),
            float(second["minimum"][0]) - float(first["maximum"][0]),
            0.0,
        )
        dy = max(
            float(first["minimum"][1]) - float(second["maximum"][1]),
            float(second["minimum"][1]) - float(first["maximum"][1]),
            0.0,
        )
        return math.hypot(dx, dy)

    @staticmethod
    def _segments_intersect(
        a: Sequence[float],
        b: Sequence[float],
        c: Sequence[float],
        d: Sequence[float],
        tolerance: float,
    ) -> bool:
        def cross(p: Sequence[float], q: Sequence[float], r: Sequence[float]) -> float:
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

        def sign(value: float) -> int:
            if abs(value) <= tolerance:
                return 0
            return 1 if value > 0 else -1

        return (
            sign(cross(a, b, c)) * sign(cross(a, b, d)) <= 0
            and sign(cross(c, d, a)) * sign(cross(c, d, b)) <= 0
            and CadObjectGroupBuilder._bounds_distance(
                {"minimum": [min(a[0], b[0]), min(a[1], b[1])], "maximum": [max(a[0], b[0]), max(a[1], b[1])]},
                {"minimum": [min(c[0], d[0]), min(c[1], d[1])], "maximum": [max(c[0], d[0]), max(c[1], d[1])]},
            ) <= tolerance
        )

    @staticmethod
    def _make_group(
        source_sha256: str,
        category: str,
        members: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        candidate_ids = sorted(item["candidate_id"] for item in members)
        digest = hashlib.sha256(
            f"{source_sha256}:{category}:{','.join(candidate_ids)}".encode("utf-8")
        ).hexdigest()[:24]
        entity_types = Counter(item["source_entity_type"] for item in members)
        minimum = [min(item["bounds"]["minimum"][axis] for item in members) for axis in (0, 1)]
        maximum = [max(item["bounds"]["maximum"][axis] for item in members) for axis in (0, 1)]
        block_group = len(members) == 1 and bool(members[0]["requires_block_expansion"])
        return {
            "group_id": "cadgroup-" + digest,
            "category": category,
            "group_kind": "block-instance-candidate" if block_group else "connected-geometry-candidate",
            "candidate_count": len(members),
            "candidate_ids": candidate_ids,
            "source_layers": sorted({item["source_layer"] for item in members}),
            "source_entity_type_counts": dict(sorted(entity_types.items())),
            "bounds": {"minimum": minimum, "maximum": maximum},
            "merge_confidence": 0.9 if block_group else 0.7 if len(members) > 1 else 0.55,
            "domain_validation_status": "pending",
            "quantity_status": "not-ready",
        }
