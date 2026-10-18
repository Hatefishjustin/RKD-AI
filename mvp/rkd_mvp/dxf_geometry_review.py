from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from .dxf_intake import DxfParseError, _as_float, _as_int, _decode_dxf, _field, _pairs, _records, _sections


LINEWORK_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "POINT", "INSERT"}


def _points_from_record(record: list[tuple[int, str]]) -> list[list[float]]:
    entity_type = _field(record, 0, "").strip().upper()
    if entity_type == "LINE":
        values = []
        for x_code, y_code in ((10, 20), (11, 21)):
            x = _as_float(_field(record, x_code))
            y = _as_float(_field(record, y_code))
            if x is not None and y is not None:
                values.append([x, y])
        return values
    if entity_type == "LWPOLYLINE":
        xs = [_as_float(value) for code, value in record if code == 10]
        ys = [_as_float(value) for code, value in record if code == 20]
        return [[x, y] for x, y in zip(xs, ys) if x is not None and y is not None]
    if entity_type in {"CIRCLE", "ARC", "ELLIPSE"}:
        x = _as_float(_field(record, 10))
        y = _as_float(_field(record, 20))
        if x is None or y is None:
            return []
        radius = _as_float(_field(record, 40)) or 0.0
        if radius <= 0:
            return [[x, y]]
        if entity_type == "ARC":
            start = math.radians(_as_float(_field(record, 50)) or 0.0)
            end = math.radians(_as_float(_field(record, 51)) or 360.0)
            while end < start:
                end += math.tau
            angles = [start + (end - start) * index / 15 for index in range(16)]
        else:
            angles = [math.tau * index / 24 for index in range(24)]
        return [[x + radius * math.cos(angle), y + radius * math.sin(angle)] for angle in angles]
    if entity_type == "SPLINE":
        xs = [_as_float(value) for code, value in record if code == 10]
        ys = [_as_float(value) for code, value in record if code == 20]
        return [[x, y] for x, y in zip(xs, ys) if x is not None and y is not None]
    x = _as_float(_field(record, 10))
    y = _as_float(_field(record, 20))
    return [[x, y]] if x is not None and y is not None else []


def _bounds(points: list[list[float]]) -> dict[str, list[float]] | None:
    if not points:
        return None
    return {
        "minimum": [min(point[0] for point in points), min(point[1] for point in points)],
        "maximum": [max(point[0] for point in points), max(point[1] for point in points)],
    }


def _intersects(bounds: Mapping[str, list[float]], target: Mapping[str, list[float]]) -> bool:
    return not (
        bounds["maximum"][0] < target["minimum"][0]
        or bounds["minimum"][0] > target["maximum"][0]
        or bounds["maximum"][1] < target["minimum"][1]
        or bounds["minimum"][1] > target["maximum"][1]
    )


class DxfGeometryReviewBuilder:
    """Builds unapproved direct-entity evidence for a DXF main-plan comparison."""

    def build(
        self,
        dxf_path: str | Path,
        plan_candidates: Mapping[str, Any],
        semantic_rules: Mapping[str, Any],
        dwg_plan_candidates: Mapping[str, Any],
    ) -> dict[str, Any]:
        if plan_candidates.get("status") != "candidate-extraction-complete":
            raise ValueError("DXF geometry review requires a completed DWG plan profile.")
        path = Path(dxf_path).resolve()
        raw = path.read_bytes()
        text, encoding = _decode_dxf(raw)
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        sections = _sections(list(_pairs(lines)))
        target = plan_candidates["target_region"]["bounds"]
        rules = self._rules(semantic_rules)
        records = _records(sections.get("ENTITIES", []))
        blocks = self._blocks(sections.get("BLOCKS", []))
        counts = Counter()
        category_counts = Counter()
        layer_counts = Counter()
        skipped = Counter()
        evidence: list[dict[str, Any]] = []
        block_expansion_statuses = Counter()
        expanded_leaf_types = Counter()
        expanded_point_count = 0
        for index, record in enumerate(records):
            entity_type = _field(record, 0, "").strip().upper()
            layer = self._text(_field(record, 8, "0").strip() or "0")
            space = _as_int(_field(record, 67, "0") or "0")
            layout = self._text(_field(record, 410, "Model").strip())
            if space == 1 or layout.casefold() != "model":
                skipped["paper-space"] += 1
                continue
            if entity_type not in LINEWORK_TYPES:
                skipped[entity_type or "unknown"] += 1
                continue
            points = _points_from_record(record)
            geometry_bounds = _bounds(points)
            if geometry_bounds is None:
                skipped["missing-coordinate"] += 1
                continue
            if not _intersects(geometry_bounds, target):
                skipped["outside-main-plan"] += 1
                continue
            rule = self._find_rule(layer, rules)
            category = rule["category"] if rule else "cad.unclassified"
            scope = rule["scope_disposition"] if rule else "undetermined"
            handle_text = _field(record, 5)
            handle = int(handle_text, 16) if handle_text and re.fullmatch(r"[0-9A-Fa-f]+", handle_text.strip()) else index + 1
            counts["direct_entity_count"] += 1
            counts[f"entity_type:{entity_type}"] += 1
            category_counts[category] += 1
            layer_counts[layer] += 1
            expansion = None
            if entity_type == "INSERT":
                block_name = self._text(_field(record, 2, "").strip())
                expansion = self._expand_block(block_name, record, blocks, max_depth=16)
                block_expansion_statuses[expansion["status"]] += 1
                expanded_point_count += len(expansion["points"])
                expanded_leaf_types.update(expansion["leaf_types"])
            if len(evidence) < 5000:
                item = {
                    "entity_handle": handle,
                    "entity_type": entity_type,
                    "layer": layer,
                    "category": category,
                    "scope_disposition": scope,
                    "bounds": geometry_bounds,
                    "point_count": len(points),
                    "geometry_status": "direct-model-geometry-candidate" if entity_type != "INSERT" else "block-insertion-point-only",
                    "requires_block_expansion": entity_type == "INSERT",
                    "eligible_for_current_scope": scope == "included-design-evidence",
                }
                if expansion is not None:
                    item["block_expansion"] = {
                        "status": expansion["status"],
                        "expanded_point_count": len(expansion["points"]),
                        "expanded_bounds": _bounds(expansion["points"]),
                        "leaf_entity_type_counts": dict(sorted(expansion["leaf_types"].items())),
                        "issue_counts": dict(sorted(expansion["issues"].items())),
                    }
                evidence.append(item)

        dwg_category_counts = Counter(
            item.get("category") for item in dwg_plan_candidates.get("candidates", [])
            if item.get("eligible_for_current_scope") is True or item.get("scope_disposition") == "excluded-by-project-decision"
        )
        comparison_categories = sorted(set(category_counts) | set(dwg_category_counts))
        category_comparison = [
            {
                "category": category,
                "dxf_direct_entity_count": category_counts.get(category, 0),
                "dwg_candidate_count": dwg_category_counts.get(category, 0),
                "delta_dxf_minus_dwg": category_counts.get(category, 0) - dwg_category_counts.get(category, 0),
                "status": "match" if category_counts.get(category, 0) == dwg_category_counts.get(category, 0) else "difference",
            }
            for category in comparison_categories
        ]
        differences = [item["category"] for item in category_comparison if item["status"] == "difference"]
        return {
            "contract_version": "1.0",
            "source_asset_id": "drawing-cad-01-dxf-2013",
            "source_sha256": hashlib.sha256(raw).hexdigest().upper(),
            "dxf_parser": {"name": "RKD ASCII DXF geometry reader", "version": "1.0", "encoding": encoding},
            "plan_profile_id": plan_candidates["profile_id"],
            "target_region": plan_candidates["target_region"],
            "status": "geometry-review-created",
            "summary": {
                "dxf_model_entity_record_count": len(records),
                "dxf_direct_entity_in_main_plan_count": counts["direct_entity_count"],
                "dxf_current_scope_direct_entity_count": sum(
                    value for category, value in category_counts.items()
                    if any(
                        rule.get("category") == category and rule.get("scope_disposition") == "included-design-evidence"
                        for rule in rules
                    )
                ),
                "dxf_block_insertion_point_count": counts.get("entity_type:INSERT", 0),
                "dxf_block_expansion_status_counts": dict(sorted(block_expansion_statuses.items())),
                "dxf_expanded_block_point_count": expanded_point_count,
                "dxf_expanded_block_leaf_entity_type_counts": dict(sorted(expanded_leaf_types.items())),
                "skipped_counts": dict(sorted(skipped.items())),
                "category_difference_count": len(differences),
                "created_domain_object_count": 0,
                "quantity_ready_count": 0,
                "promotion_status": "not-approved",
            },
            "category_comparison": category_comparison,
            "dxf_layer_counts": dict(sorted(layer_counts.items())),
            "evidence_sample": evidence,
            "warnings": [
                {
                    "code": "DXF_BLOCK_EXPANSION_IS_LIMITED_REVIEW",
                    "message": "Basic 2D BLOCK/INSERT base-point, scale, rotation, and nested transforms are expanded for evidence; arrays, non-planar extrusion, full HATCH topology, and professional object semantics still require a second CAD engine.",
                },
                {
                    "code": "GEOMETRY_CANDIDATES_NOT_DOMAIN_OBJECTS",
                    "message": "Evidence remains unapproved geometry; no walls, doors, rooms, quantities, or construction status were created.",
                },
                {
                    "code": "DXF_AND_DWG_LAYER_NAME_ENCODING_MAY_DIFFER",
                    "message": "Category comparison is more reliable than raw layer-name comparison when one parser emits replacement characters for Chinese names.",
                },
            ],
        }

    @staticmethod
    def _text(value: str) -> str:
        return re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda match: chr(int(match.group(1), 16)), value)

    @classmethod
    def _rules(cls, payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        return list(payload.get("rules", []))

    @classmethod
    def _find_rule(cls, layer: str, rules: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        for rule in rules:
            if layer in {cls._text(name) for name in rule.get("exact_names", [])}:
                return rule
            pattern = rule.get("pattern")
            if pattern and re.search(pattern, layer, re.IGNORECASE):
                return rule
        return None

    @classmethod
    def _blocks(cls, section: list[tuple[int, str]]) -> dict[str, dict[str, Any]]:
        blocks: dict[str, dict[str, Any]] = {}
        current: dict[str, Any] | None = None
        for record in _records(section):
            kind = _field(record, 0, "").strip().upper()
            if kind == "BLOCK":
                name = cls._text(_field(record, 2, "").strip())
                current = {
                    "name": name,
                    "base": [
                        _as_float(_field(record, 10)) or 0.0,
                        _as_float(_field(record, 20)) or 0.0,
                    ],
                    "entities": [],
                }
                blocks[name] = current
            elif kind == "ENDBLK":
                current = None
            elif current is not None and kind:
                current["entities"].append(record)
        return blocks

    @classmethod
    def _expand_block(
        cls,
        block_name: str,
        insert: list[tuple[int, str]],
        blocks: Mapping[str, Mapping[str, Any]],
        max_depth: int,
    ) -> dict[str, Any]:
        leaf_types: Counter[str] = Counter()
        points: list[list[float]] = []
        issues: Counter[str] = Counter()

        def matrix_for(record: list[tuple[int, str]], block: Mapping[str, Any]) -> tuple[float, float, float, float, float, float]:
            insertion = (_as_float(_field(record, 10)) or 0.0, _as_float(_field(record, 20)) or 0.0)
            sx = _as_float(_field(record, 41)) or 1.0
            sy = _as_float(_field(record, 42)) or sx
            rotation = math.radians(_as_float(_field(record, 50)) or 0.0)
            cosine, sine = math.cos(rotation), math.sin(rotation)
            a, b, c, d = cosine * sx, sine * sx, -sine * sy, cosine * sy
            base = block.get("base", [0.0, 0.0])
            return a, b, c, d, insertion[0] - a * base[0] - c * base[1], insertion[1] - b * base[0] - d * base[1]

        def compose(parent: tuple[float, float, float, float, float, float], child: tuple[float, float, float, float, float, float]):
            pa, pb, pc, pd, ptx, pty = parent
            ca, cb, cc, cd, ctx, cty = child
            return (
                pa * ca + pc * cb, pb * ca + pd * cb,
                pa * cc + pc * cd, pb * cc + pd * cd,
                pa * ctx + pc * cty + ptx, pb * ctx + pd * cty + pty,
            )

        def transform(point: list[float], matrix: tuple[float, float, float, float, float, float]) -> list[float]:
            a, b, c, d, tx, ty = matrix
            return [a * point[0] + c * point[1] + tx, b * point[0] + d * point[1] + ty]

        def visit(name: str, record: list[tuple[int, str]], parent: tuple[float, float, float, float, float, float], depth: int, active: frozenset[str]) -> None:
            if depth > max_depth:
                issues["maximum-depth-exceeded"] += 1
                return
            block = blocks.get(name)
            if block is None:
                issues["missing-block-definition"] += 1
                return
            if name in active:
                issues["cyclic-block-reference"] += 1
                return
            child_matrix = matrix_for(record, block)
            matrix = compose(parent, child_matrix)
            for entity in block.get("entities", []):
                kind = _field(entity, 0, "").strip().upper()
                if kind == "INSERT":
                    nested_name = cls._text(_field(entity, 2, "").strip())
                    visit(nested_name, entity, matrix, depth + 1, active | {name})
                    continue
                entity_points = _points_from_record(entity)
                if not entity_points:
                    issues[f"skipped-{kind or 'unknown'}"] += 1
                    continue
                leaf_types[kind] += 1
                points.extend(transform(point, matrix) for point in entity_points)

        visit(block_name, insert, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), 1, frozenset())
        status = "expanded" if points and not issues else ("partially-expanded" if points else "not-expanded")
        return {"status": status, "points": points, "leaf_types": leaf_types, "issues": dict(issues)}
