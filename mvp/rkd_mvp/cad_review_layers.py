from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .cad_plan_candidates import CadPlanCandidateExtractor


class CadReviewLayerAnalyzer:
    """Places system-review layer entities in the localized model-space plan."""

    def analyze(
        self,
        payload: Mapping[str, Any],
        inspection: Mapping[str, Any],
        semantic_mapping: Mapping[str, Any],
        plan_candidates: Mapping[str, Any],
        max_depth: int = 32,
    ) -> dict[str, Any]:
        self._validate_inputs(payload, inspection, semantic_mapping, plan_candidates)
        geometry = CadPlanCandidateExtractor
        objects = payload["OBJECTS"]
        object_by_handle = {
            handle: item
            for item in objects
            if isinstance(item, dict)
            if (handle := geometry._last_handle(item.get("handle"))) is not None
        }
        block_headers = {
            handle: item
            for handle, item in object_by_handle.items()
            if item.get("object") == "BLOCK_HEADER"
        }
        layer_objects = [
            item for item in objects
            if isinstance(item, dict) and item.get("object") == "LAYER"
        ]
        layer_names = inspection["geometry_metadata"]["layer_names"]
        if len(layer_objects) != len(layer_names):
            raise ValueError("Layer object order no longer matches the inspected layer list.")
        layer_by_handle = {
            geometry._last_handle(layer["handle"]): name
            for layer, name in zip(layer_objects, layer_names)
        }
        review_mappings = [
            item for item in semantic_mapping["layer_mappings"]
            if item.get("verification_status") == "needs-system-review"
        ]
        review_names = {item["layer_name"] for item in review_mappings}
        target_region = plan_candidates["target_region"]["bounds"]
        state = {
            name: {
                "unique_model_handles": set(),
                "plan_unique_handles": set(),
                "outside_unique_handles": set(),
                "plan_instance_count": 0,
                "outside_instance_count": 0,
                "coordinate_missing_instance_count": 0,
                "plan_entity_types": Counter(),
                "outside_entity_types": Counter(),
                "samples": [],
            }
            for name in review_names
        }
        traversal_issues: Counter[str] = Counter()
        maximum_depth_seen = 0

        def visit(
            entity: Mapping[str, Any],
            matrix: tuple[float, float, float, float, float, float],
            depth: int,
            active_blocks: frozenset[int],
        ) -> None:
            nonlocal maximum_depth_seen
            maximum_depth_seen = max(maximum_depth_seen, depth)
            handle = geometry._last_handle(entity.get("handle"))
            layer_name = layer_by_handle.get(geometry._last_handle(entity.get("layer")))
            if layer_name in state and handle is not None:
                layer_state = state[layer_name]
                layer_state["unique_model_handles"].add(handle)
                local_points = geometry._entity_points(entity)
                if local_points:
                    points = [geometry._transform_point(point, matrix) for point in local_points]
                    bounds = geometry._bounds(points)
                    inside = geometry._intersects(bounds, target_region)
                    prefix = "plan" if inside else "outside"
                    layer_state[f"{prefix}_instance_count"] += 1
                    layer_state[f"{prefix}_unique_handles"].add(handle)
                    layer_state[f"{prefix}_entity_types"][str(entity["entity"])] += 1
                    if inside and len(layer_state["samples"]) < 25:
                        layer_state["samples"].append({
                            "source_entity_handle": handle,
                            "source_entity_type": str(entity["entity"]),
                            "instance_depth": depth,
                            "bounds": bounds,
                        })
                else:
                    layer_state["coordinate_missing_instance_count"] += 1

            if entity.get("entity") != "INSERT":
                return
            if depth >= max_depth:
                traversal_issues["maximum-depth-exceeded"] += 1
                return
            block_handle = geometry._last_handle(entity.get("block_header"))
            block = block_headers.get(block_handle)
            if block is None:
                traversal_issues["missing-block-definition"] += 1
                return
            if block_handle in active_blocks:
                traversal_issues["cyclic-block-reference"] += 1
                return
            if not geometry._is_supported_planar_extrusion(entity.get("extrusion")):
                traversal_issues["unsupported-nonplanar-extrusion"] += 1
                return
            row_count = int(entity.get("row_count") or 1)
            column_count = int(entity.get("column_count") or 1)
            if row_count != 1 or column_count != 1:
                traversal_issues["unsupported-insert-array"] += 1
                return
            child_matrix = geometry._compose_matrix(
                matrix,
                geometry._insert_matrix(entity, block),
            )
            descendants = active_blocks | {block_handle}
            for reference in block.get("entities", []) or []:
                child = object_by_handle.get(geometry._last_handle(reference))
                if not child or not child.get("entity"):
                    traversal_issues["missing-block-entity"] += 1
                    continue
                visit(child, child_matrix, depth + 1, descendants)

        model_header = next(
            (
                block for block in block_headers.values()
                if block.get("name") == "*Model_Space"
            ),
            None,
        )
        if model_header is None:
            raise ValueError("DWG payload has no model-space block header.")
        identity = geometry._identity_matrix()
        for reference in model_header.get("entities", []) or []:
            entity = object_by_handle.get(geometry._last_handle(reference))
            if entity and entity.get("entity"):
                visit(entity, identity, 0, frozenset())

        layers = []
        for mapping in review_mappings:
            name = mapping["layer_name"]
            layer_state = state[name]
            unique_model = len(layer_state["unique_model_handles"])
            declared_reachable = int(mapping["reachable_entity_count"])
            context_counts = mapping.get("block_context_counts", {})
            declared_model = int(context_counts.get("model-reachable", unique_model))
            declared_model += int(context_counts.get("model-and-paper-reachable", 0))
            declared_paper_only = int(context_counts.get("paper-reachable", 0))
            plan_instances = layer_state["plan_instance_count"]
            layers.append({
                "layer_name": name,
                "category": mapping["category"],
                "scope_disposition": mapping["scope_disposition"],
                "storage_entity_count": mapping["entity_count"],
                "declared_reachable_entity_count": declared_reachable,
                "declared_model_reachable_entity_count": declared_model,
                "declared_paper_only_reachable_entity_count": declared_paper_only,
                "model_reachable_unique_source_entity_count": unique_model,
                "noninstantiated_model_source_entity_count": max(0, declared_model - unique_model),
                "primary_plan_instance_count": plan_instances,
                "primary_plan_unique_source_entity_count": len(layer_state["plan_unique_handles"]),
                "outside_primary_plan_instance_count": layer_state["outside_instance_count"],
                "outside_primary_plan_unique_source_entity_count": len(layer_state["outside_unique_handles"]),
                "coordinate_missing_instance_count": layer_state["coordinate_missing_instance_count"],
                "primary_plan_entity_type_counts": dict(sorted(layer_state["plan_entity_types"].items())),
                "outside_primary_plan_entity_type_counts": dict(sorted(layer_state["outside_entity_types"].items())),
                "primary_plan_samples": layer_state["samples"],
                "disposition": (
                    "evidence-only-review-required"
                    if plan_instances
                    else "not-present-in-primary-plan"
                ),
            })

        return {
            "contract_version": "1.0",
            "source_asset_id": inspection["source_asset_id"],
            "source_sha256": inspection["sha256"],
            "semantic_mapping_version": semantic_mapping["mapping_version"],
            "plan_profile_id": plan_candidates["profile_id"],
            "status": "review-layer-spatial-analysis-complete",
            "summary": {
                "review_layer_count": len(layers),
                "declared_reachable_entity_count": sum(item["declared_reachable_entity_count"] for item in layers),
                "declared_model_reachable_entity_count": sum(item["declared_model_reachable_entity_count"] for item in layers),
                "declared_paper_only_reachable_entity_count": sum(item["declared_paper_only_reachable_entity_count"] for item in layers),
                "model_reachable_unique_source_entity_count": sum(item["model_reachable_unique_source_entity_count"] for item in layers),
                "noninstantiated_model_source_entity_count": sum(item["noninstantiated_model_source_entity_count"] for item in layers),
                "primary_plan_instance_count": sum(item["primary_plan_instance_count"] for item in layers),
                "outside_primary_plan_instance_count": sum(item["outside_primary_plan_instance_count"] for item in layers),
                "coordinate_missing_instance_count": sum(item["coordinate_missing_instance_count"] for item in layers),
                "maximum_nested_depth_seen": maximum_depth_seen,
                "traversal_issue_counts": dict(sorted(traversal_issues.items())),
                "user_confirmation_required_now": False,
            },
            "layers": layers,
            "warnings": [
                {
                    "code": "REVIEW_LAYERS_NOT_PROMOTED",
                    "message": "Spatial placement does not assign these legacy layers to walls, furniture, or other professional categories.",
                },
                {
                    "code": "INSTANCE_COUNTS_ARE_NOT_QUANTITIES",
                    "message": "Instance counts are diagnostic occurrences and must not be used as bill-of-quantity values.",
                },
            ],
        }

    @staticmethod
    def _validate_inputs(
        payload: Mapping[str, Any],
        inspection: Mapping[str, Any],
        semantic_mapping: Mapping[str, Any],
        plan_candidates: Mapping[str, Any],
    ) -> None:
        source_sha = inspection.get("sha256")
        if inspection.get("intake_status") != "geometry-parsed":
            raise ValueError("Review layer analysis requires geometry-parsed input.")
        if semantic_mapping.get("source_sha256") != source_sha:
            raise ValueError("Semantic mapping and inspection source hashes differ.")
        if plan_candidates.get("source_sha256") != source_sha:
            raise ValueError("Plan candidates and inspection source hashes differ.")
        if not isinstance(payload.get("OBJECTS"), list):
            raise ValueError("DWG payload has no OBJECTS list.")
