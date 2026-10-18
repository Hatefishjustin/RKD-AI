from __future__ import annotations

import hashlib
import math
import statistics
from collections import Counter
from typing import Any, Mapping, Sequence


class CadPlanCandidateExtractor:
    """Locates one plan region and emits direct-model geometry candidates."""

    def extract(
        self,
        payload: Mapping[str, Any],
        inspection: Mapping[str, Any],
        semantic_mapping: Mapping[str, Any],
        profile: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._validate_inputs(payload, inspection, semantic_mapping, profile)
        objects = payload["OBJECTS"]
        object_by_handle = {
            handle: item
            for item in objects
            if isinstance(item, dict)
            if (handle := self._last_handle(item.get("handle"))) is not None
        }
        block_headers = {
            handle: item
            for item in objects
            if isinstance(item, dict) and item.get("object") == "BLOCK_HEADER"
            if (handle := self._last_handle(item.get("handle"))) is not None
        }
        layer_names = inspection["geometry_metadata"]["layer_names"]
        layer_objects = [
            item for item in objects
            if isinstance(item, dict) and item.get("object") == "LAYER"
        ]
        if len(layer_objects) != len(layer_names):
            raise ValueError("Layer object order no longer matches the inspected layer list.")
        layer_by_handle = {
            self._last_handle(layer["handle"]): name
            for layer, name in zip(layer_objects, layer_names)
        }
        mapping_by_layer = {
            item["layer_name"]: item for item in semantic_mapping["layer_mappings"]
        }

        model_header = next(
            (
                item for item in objects
                if isinstance(item, dict)
                and item.get("object") == "BLOCK_HEADER"
                and item.get("name") == "*Model_Space"
            ),
            None,
        )
        if model_header is None:
            raise ValueError("DWG payload has no model-space block header.")
        model_handles = {
            handle
            for reference in model_header.get("entities", []) or []
            if (handle := self._last_handle(reference)) is not None
        }

        target_region, anchor_evidence = self._locate_region(
            model_handles,
            object_by_handle,
            layer_by_handle,
            profile,
        )
        candidates: list[dict[str, Any]] = []
        skipped_without_coordinates: Counter[str] = Counter()
        outside_region: Counter[str] = Counter()
        category_counts: Counter[str] = Counter()
        layer_counts: Counter[str] = Counter()
        scope_counts: Counter[str] = Counter()
        expansion_status_counts: Counter[str] = Counter()

        for handle in sorted(model_handles):
            entity = object_by_handle.get(handle)
            if not entity or not entity.get("entity"):
                continue
            layer_name = layer_by_handle.get(self._last_handle(entity.get("layer")))
            mapping = mapping_by_layer.get(layer_name)
            if not mapping or mapping.get("layer_role") != "professional":
                continue
            expansion = None
            points = self._entity_points(entity)
            if entity["entity"] == "INSERT":
                expansion = self._expand_insert_geometry(
                    entity,
                    object_by_handle,
                    block_headers,
                    max_depth=int(profile.get("max_block_expansion_depth", 16)),
                )
                if expansion["points"]:
                    points = expansion["points"]
            if not points:
                skipped_without_coordinates[layer_name or "<unknown>"] += 1
                continue
            bounds = self._bounds(points)
            if not self._intersects(bounds, target_region):
                outside_region[layer_name] += 1
                continue
            scope_disposition = mapping["scope_disposition"]
            candidate = {
                "candidate_id": self._candidate_id(
                    inspection["sha256"],
                    handle,
                    mapping["category"],
                ),
                "source_entity_handle": handle,
                "source_entity_type": entity["entity"],
                "source_layer": layer_name,
                "category": mapping["category"],
                "scope_disposition": scope_disposition,
                "mapping_confidence": mapping["confidence"],
                "bounds": bounds,
                "point_count": len(points),
                "geometry_points": [
                    [round(point[0], 6), round(point[1], 6)] for point in points
                ],
                "source_geometry_closed": self._source_geometry_closed(entity),
                "geometry_status": "direct-model-geometry-candidate",
                "requires_block_expansion": entity["entity"] == "INSERT",
                "eligible_for_current_scope": scope_disposition == "included-design-evidence",
            }
            if entity["entity"] == "INSERT":
                candidate["referenced_block_handle"] = self._last_handle(entity.get("block_header"))
                candidate["root_insertion_point"] = self._point2(entity.get("ins_pt"))
                candidate["geometry_status"] = (
                    "block-expanded-geometry-candidate"
                    if expansion["status"] == "expanded"
                    else "block-partially-expanded-geometry-candidate"
                    if expansion["points"]
                    else "block-insertion-point-only"
                )
                candidate["block_expansion"] = {
                    key: value for key, value in expansion.items() if key != "points"
                }
                expansion_status_counts[expansion["status"]] += 1
            candidates.append(candidate)
            category_counts[mapping["category"]] += 1
            layer_counts[layer_name] += 1
            scope_counts[scope_disposition] += 1

        source_sha = inspection["sha256"]
        return {
            "contract_version": "1.0",
            "profile_id": profile["profile_id"],
            "source_asset_id": inspection["source_asset_id"],
            "source_sha256": source_sha,
            "semantic_mapping_version": semantic_mapping["mapping_version"],
            "status": "candidate-extraction-complete",
            "target_region": {
                "coordinate_space": "dwg-model-space",
                "units": inspection["geometry_metadata"]["drawing_units"]["name"],
                "bounds": target_region,
                "size": {
                    "x": round(target_region["maximum"][0] - target_region["minimum"][0], 6),
                    "y": round(target_region["maximum"][1] - target_region["minimum"][1], 6),
                },
                "anchor_evidence": anchor_evidence,
                "corroborating_evidence": profile.get("corroborating_evidence", []),
                "construction_verification_status": "drawing-cross-checked-not-site-verified",
            },
            "summary": {
                "direct_model_candidate_count": len(candidates),
                "current_scope_candidate_count": scope_counts["included-design-evidence"],
                "excluded_scope_candidate_count": scope_counts["excluded-by-project-decision"],
                "other_non_current_scope_candidate_count": (
                    len(candidates)
                    - scope_counts["included-design-evidence"]
                    - scope_counts["excluded-by-project-decision"]
                ),
                "scope_disposition_candidate_counts": dict(sorted(scope_counts.items())),
                "block_insertion_candidate_count": sum(item["requires_block_expansion"] for item in candidates),
                "block_expansion_status_counts": dict(sorted(expansion_status_counts.items())),
                "category_candidate_counts": dict(sorted(category_counts.items())),
                "layer_candidate_counts": dict(sorted(layer_counts.items())),
                "outside_region_counts": dict(sorted(outside_region.items())),
                "skipped_without_coordinate_counts": dict(sorted(skipped_without_coordinates.items())),
                "nested_block_geometry_status": self._aggregate_expansion_status(expansion_status_counts),
                "user_confirmation_required_now": False,
            },
            "candidates": candidates,
            "warnings": [
                {
                    "code": "PRIMITIVES_ARE_NOT_DOMAIN_OBJECTS",
                    "message": "Candidate primitives must be merged and validated before becoming walls, doors, furniture, or quantities.",
                },
                {
                    "code": "BLOCK_TRANSFORMS_REQUIRE_SECONDARY_VALIDATION",
                    "message": "Block geometry was expanded with 2D insertion, scale, rotation, and base-point transforms but still requires a second CAD engine for production verification.",
                },
                {
                    "code": "DRAWING_DIMENSIONS_NOT_SITE_MEASUREMENTS",
                    "message": "The located region is supported by DWG/PDF drawing dimensions but is not a site measurement.",
                },
            ],
        }

    def _locate_region(
        self,
        model_handles: set[int],
        object_by_handle: Mapping[int, Mapping[str, Any]],
        layer_by_handle: Mapping[int | None, str],
        profile: Mapping[str, Any],
    ) -> tuple[dict[str, list[float]], list[dict[str, Any]]]:
        expected = sorted(float(value) for value in profile["expected_dimensions_mm"])
        tolerance = float(profile["dimension_tolerance_mm"])
        evidence: list[dict[str, Any]] = []
        accepted_bounds: list[dict[str, list[float]]] = []
        for layer_name in profile["primary_anchor_layers"]:
            points: list[tuple[float, float]] = []
            entity_count = 0
            for handle in model_handles:
                entity = object_by_handle.get(handle)
                if not entity or not entity.get("entity"):
                    continue
                if layer_by_handle.get(self._last_handle(entity.get("layer"))) != layer_name:
                    continue
                entity_count += 1
                points.extend(self._entity_points(entity))
            if not points:
                evidence.append({
                    "layer_name": layer_name,
                    "status": "missing-coordinate-evidence",
                    "entity_count": entity_count,
                })
                continue
            bounds = self._bounds(points)
            dimensions = sorted([
                bounds["maximum"][0] - bounds["minimum"][0],
                bounds["maximum"][1] - bounds["minimum"][1],
            ])
            matched = all(abs(actual - wanted) <= tolerance for actual, wanted in zip(dimensions, expected))
            evidence.append({
                "layer_name": layer_name,
                "status": "matched" if matched else "dimension-mismatch",
                "entity_count": entity_count,
                "bounds": bounds,
                "sorted_dimensions_mm": [round(value, 6) for value in dimensions],
            })
            if matched:
                accepted_bounds.append(bounds)

        minimum_matches = int(profile["minimum_anchor_matches"])
        if len(accepted_bounds) < minimum_matches:
            raise ValueError(
                f"Only {len(accepted_bounds)} plan anchors matched; {minimum_matches} are required."
            )
        region = {
            "minimum": [
                statistics.median(item["minimum"][axis] for item in accepted_bounds)
                for axis in (0, 1)
            ],
            "maximum": [
                statistics.median(item["maximum"][axis] for item in accepted_bounds)
                for axis in (0, 1)
            ],
        }
        consensus_tolerance = float(profile.get("anchor_consensus_tolerance_mm", tolerance))
        for bounds in accepted_bounds:
            deviations = [
                abs(bounds[edge][axis] - region[edge][axis])
                for edge in ("minimum", "maximum")
                for axis in (0, 1)
            ]
            if max(deviations) > consensus_tolerance:
                raise ValueError("Plan anchors match dimensions but disagree on model-space location.")
        return region, evidence

    @staticmethod
    def _entity_points(entity: Mapping[str, Any]) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []

        def add(value: Any) -> None:
            if (
                isinstance(value, Sequence)
                and not isinstance(value, (str, bytes))
                and len(value) >= 2
                and isinstance(value[0], (int, float))
                and isinstance(value[1], (int, float))
            ):
                points.append((float(value[0]), float(value[1])))
            elif isinstance(value, Mapping) and isinstance(value.get("x"), (int, float)) and isinstance(value.get("y"), (int, float)):
                points.append((float(value["x"]), float(value["y"])))

        for key in (
            "start", "end", "ins_pt", "point", "def_pt", "text_midpt",
            "xline1_pt", "xline2_pt",
        ):
            add(entity.get(key))
        for key in ("points", "ctrl_pts", "fit_pts", "pts"):
            for value in entity.get(key, []) or []:
                add(value)
        for path in entity.get("paths", []) or []:
            if not isinstance(path, Mapping):
                continue
            for value in path.get("polyline_paths", []) or []:
                if isinstance(value, Mapping):
                    add(value.get("point"))
            for value in path.get("vertices", []) or []:
                add(value.get("point") if isinstance(value, Mapping) else value)
            for segment in path.get("segs", []) or []:
                if not isinstance(segment, Mapping):
                    continue
                for key in ("first_endpoint", "second_endpoint", "center"):
                    add(segment.get(key))
                for key in ("control_points", "fit_points"):
                    for value in segment.get(key, []) or []:
                        add(value.get("point") if isinstance(value, Mapping) else value)
        if entity.get("entity") == "CIRCLE":
            center = entity.get("center")
            radius = entity.get("radius")
            if isinstance(center, Sequence) and len(center) >= 2 and isinstance(radius, (int, float)):
                for index in range(33):
                    radians = 2 * math.pi * index / 32
                    points.append((
                        float(center[0]) + float(radius) * math.cos(radians),
                        float(center[1]) + float(radius) * math.sin(radians),
                    ))
        if entity.get("entity") == "ARC":
            center = entity.get("center")
            radius = entity.get("radius")
            start_angle = entity.get("start_angle")
            end_angle = entity.get("end_angle")
            if (
                isinstance(center, Sequence)
                and len(center) >= 2
                and isinstance(radius, (int, float))
                and isinstance(start_angle, (int, float))
                and isinstance(end_angle, (int, float))
            ):
                start = float(start_angle)
                end = float(end_angle)
                while end < start:
                    end += 2 * math.pi
                sample_count = max(2, math.ceil((end - start) / (math.pi / 32)))
                for index in range(sample_count + 1):
                    radians = start + (end - start) * index / sample_count
                    points.append((
                        float(center[0]) + float(radius) * math.cos(radians),
                        float(center[1]) + float(radius) * math.sin(radians),
                    ))
        return points

    @classmethod
    def _expand_insert_geometry(
        cls,
        root_insert: Mapping[str, Any],
        object_by_handle: Mapping[int, Mapping[str, Any]],
        block_headers: Mapping[int, Mapping[str, Any]],
        max_depth: int,
    ) -> dict[str, Any]:
        points: list[tuple[float, float]] = []
        leaf_types: Counter[str] = Counter()
        skipped_types: Counter[str] = Counter()
        issue_counts: Counter[str] = Counter()
        maximum_depth = 0

        def visit(
            insert: Mapping[str, Any],
            parent_matrix: tuple[float, float, float, float, float, float],
            depth: int,
            active_blocks: frozenset[int],
        ) -> None:
            nonlocal maximum_depth
            maximum_depth = max(maximum_depth, depth)
            if depth > max_depth:
                issue_counts["maximum-depth-exceeded"] += 1
                return
            block_handle = cls._last_handle(insert.get("block_header"))
            block = block_headers.get(block_handle)
            if block is None:
                issue_counts["missing-block-definition"] += 1
                return
            if block_handle in active_blocks:
                issue_counts["cyclic-block-reference"] += 1
                return
            if not cls._is_supported_planar_extrusion(insert.get("extrusion")):
                issue_counts["unsupported-nonplanar-extrusion"] += 1
                return
            row_count = int(insert.get("row_count") or 1)
            column_count = int(insert.get("column_count") or 1)
            if row_count != 1 or column_count != 1:
                issue_counts["unsupported-insert-array"] += 1
                return
            matrix = cls._compose_matrix(
                parent_matrix,
                cls._insert_matrix(insert, block),
            )
            descendants = active_blocks | {block_handle}
            for reference in block.get("entities", []) or []:
                entity = object_by_handle.get(cls._last_handle(reference))
                if not entity or not entity.get("entity"):
                    issue_counts["missing-block-entity"] += 1
                    continue
                entity_type = str(entity["entity"])
                if entity_type == "INSERT":
                    visit(entity, matrix, depth + 1, descendants)
                    continue
                leaf_types[entity_type] += 1
                local_points = cls._entity_points(entity)
                if not local_points:
                    skipped_types[entity_type] += 1
                    continue
                points.extend(cls._transform_point(point, matrix) for point in local_points)

        visit(root_insert, cls._identity_matrix(), 1, frozenset())
        status = "expanded"
        if issue_counts or skipped_types:
            status = "partially-expanded" if points else "not-expanded"
        elif not points:
            status = "not-expanded"
        return {
            "status": status,
            "expanded_point_count": len(points),
            "leaf_entity_count": sum(leaf_types.values()),
            "leaf_entity_type_counts": dict(sorted(leaf_types.items())),
            "skipped_leaf_entity_type_counts": dict(sorted(skipped_types.items())),
            "issue_counts": dict(sorted(issue_counts.items())),
            "maximum_nested_depth": maximum_depth,
            "points": points,
        }

    @staticmethod
    def _identity_matrix() -> tuple[float, float, float, float, float, float]:
        return 1.0, 0.0, 0.0, 1.0, 0.0, 0.0

    @classmethod
    def _insert_matrix(
        cls,
        insert: Mapping[str, Any],
        block: Mapping[str, Any],
    ) -> tuple[float, float, float, float, float, float]:
        insertion = cls._point2(insert.get("ins_pt")) or [0.0, 0.0]
        base = cls._point2(block.get("base_pt")) or [0.0, 0.0]
        scale = insert.get("scale")
        sx = float(scale[0]) if isinstance(scale, Sequence) and len(scale) >= 1 else 1.0
        sy = float(scale[1]) if isinstance(scale, Sequence) and len(scale) >= 2 else sx
        rotation = float(insert.get("rotation") or 0.0)
        cosine = math.cos(rotation)
        sine = math.sin(rotation)
        a = cosine * sx
        b = sine * sx
        c = -sine * sy
        d = cosine * sy
        extrusion = insert.get("extrusion")
        reverse_normal = (
            isinstance(extrusion, Sequence)
            and len(extrusion) >= 3
            and math.isclose(float(extrusion[2]), -1.0, abs_tol=1e-9)
        )
        ocs_x = -1.0 if reverse_normal else 1.0
        return (
            ocs_x * a,
            b,
            ocs_x * c,
            d,
            ocs_x * (insertion[0] - a * base[0] - c * base[1]),
            insertion[1] - b * base[0] - d * base[1],
        )

    @staticmethod
    def _compose_matrix(
        parent: tuple[float, float, float, float, float, float],
        child: tuple[float, float, float, float, float, float],
    ) -> tuple[float, float, float, float, float, float]:
        pa, pb, pc, pd, ptx, pty = parent
        ca, cb, cc, cd, ctx, cty = child
        return (
            pa * ca + pc * cb,
            pb * ca + pd * cb,
            pa * cc + pc * cd,
            pb * cc + pd * cd,
            pa * ctx + pc * cty + ptx,
            pb * ctx + pd * cty + pty,
        )

    @staticmethod
    def _transform_point(
        point: tuple[float, float],
        matrix: tuple[float, float, float, float, float, float],
    ) -> tuple[float, float]:
        a, b, c, d, tx, ty = matrix
        return a * point[0] + c * point[1] + tx, b * point[0] + d * point[1] + ty

    @staticmethod
    def _point2(value: Any) -> list[float] | None:
        if (
            isinstance(value, Sequence)
            and not isinstance(value, (str, bytes))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            return [float(value[0]), float(value[1])]
        return None

    @staticmethod
    def _is_supported_planar_extrusion(value: Any) -> bool:
        if value is None:
            return True
        if not isinstance(value, Sequence) or len(value) < 3:
            return False
        return (
            math.isclose(float(value[0]), 0.0, abs_tol=1e-9)
            and math.isclose(float(value[1]), 0.0, abs_tol=1e-9)
            and math.isclose(abs(float(value[2])), 1.0, abs_tol=1e-9)
        )

    @staticmethod
    def _aggregate_expansion_status(counts: Counter[str]) -> str:
        if not counts:
            return "not-applicable"
        if set(counts) == {"expanded"}:
            return "expanded"
        if counts.get("expanded") or counts.get("partially-expanded"):
            return "expanded-with-partial-candidates"
        return "not-expanded"

    @staticmethod
    def _bounds(points: Sequence[tuple[float, float]]) -> dict[str, list[float]]:
        return {
            "minimum": [min(point[0] for point in points), min(point[1] for point in points)],
            "maximum": [max(point[0] for point in points), max(point[1] for point in points)],
        }

    @staticmethod
    def _source_geometry_closed(entity: Mapping[str, Any]) -> bool | None:
        entity_type = entity.get("entity")
        if entity_type in {"CIRCLE", "HATCH"}:
            return True
        if entity_type in {"LINE", "ARC", "DIMENSION_LINEAR", "INSERT"}:
            return False if entity_type != "INSERT" else None
        if entity_type in {"LWPOLYLINE", "POLYLINE_2D", "POLYLINE_3D"}:
            flag = entity.get("flag")
            return bool(int(flag) & 1) if isinstance(flag, (int, float)) else None
        closed = entity.get("closed")
        return bool(closed) if isinstance(closed, (bool, int)) else None

    @staticmethod
    def _intersects(first: Mapping[str, Sequence[float]], second: Mapping[str, Sequence[float]]) -> bool:
        return not (
            first["maximum"][0] < second["minimum"][0]
            or first["minimum"][0] > second["maximum"][0]
            or first["maximum"][1] < second["minimum"][1]
            or first["minimum"][1] > second["maximum"][1]
        )

    @staticmethod
    def _candidate_id(source_sha256: str, handle: int, category: str) -> str:
        value = f"{source_sha256}:{handle}:{category}".encode("utf-8")
        return "cadcand-" + hashlib.sha256(value).hexdigest()[:24]

    @staticmethod
    def _last_handle(value: Any) -> int | None:
        if isinstance(value, list) and value and isinstance(value[-1], int):
            return value[-1]
        return None

    @staticmethod
    def _validate_inputs(
        payload: Mapping[str, Any],
        inspection: Mapping[str, Any],
        semantic_mapping: Mapping[str, Any],
        profile: Mapping[str, Any],
    ) -> None:
        if inspection.get("intake_status") != "geometry-parsed":
            raise ValueError("Plan candidate extraction requires geometry-parsed input.")
        if semantic_mapping.get("source_sha256") != inspection.get("sha256"):
            raise ValueError("Semantic mapping and inspection source hashes differ.")
        if profile.get("source_asset_id") != inspection.get("source_asset_id"):
            raise ValueError("Localization profile targets a different source asset.")
        if profile.get("contract_version") != "1.0":
            raise ValueError("Unsupported localization profile contract version.")
        if not isinstance(payload.get("OBJECTS"), list):
            raise ValueError("DWG payload has no OBJECTS list.")
