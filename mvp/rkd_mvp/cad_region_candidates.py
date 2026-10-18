from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Mapping


REGION_CATEGORIES = {
    "architecture.wall",
    "interior.ceiling",
    "interior.floor.finish-line",
}

LINEWORK_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE_2D", "POLYLINE_3D", "ARC", "CIRCLE"}


class CadRegionCandidateBuilder:
    """Polygonizes trusted 2D linework into unverified region candidates."""

    def build(
        self,
        plan_candidates: Mapping[str, Any],
        snap_tolerance_mm: float = 2.0,
        minimum_area_m2: float = 0.01,
    ) -> dict[str, Any]:
        if plan_candidates.get("status") != "candidate-extraction-complete":
            raise ValueError("Region extraction requires completed plan candidates.")
        if snap_tolerance_mm <= 0 or minimum_area_m2 <= 0:
            raise ValueError("Snap tolerance and minimum area must be positive.")
        try:
            import shapely
            from shapely.geometry import LineString
            from shapely.ops import polygonize_full, unary_union
        except ImportError as error:
            raise RuntimeError(
                "Shapely is required; install mvp/requirements-geometry.txt in an isolated environment."
            ) from error

        origin = plan_candidates["target_region"]["bounds"]["minimum"]
        items: list[dict[str, Any]] = []
        category_summary: list[dict[str, Any]] = []
        total_line_count = 0
        total_polygon_count = 0
        total_dangle_count = 0
        total_cut_count = 0
        total_invalid_count = 0

        for category in sorted(REGION_CATEGORIES):
            candidates = [
                item for item in plan_candidates["candidates"]
                if item.get("eligible_for_current_scope") is True
                and item.get("category") == category
            ]
            excluded_types: Counter[str] = Counter()
            lines = []
            source_candidate_ids = []
            for candidate in candidates:
                entity_type = candidate["source_entity_type"]
                points = candidate.get("geometry_points", [])
                if entity_type not in LINEWORK_TYPES or len(points) < 2:
                    excluded_types[entity_type] += 1
                    continue
                local_points = [
                    (
                        round((float(point[0]) - float(origin[0])) / snap_tolerance_mm) * snap_tolerance_mm,
                        round((float(point[1]) - float(origin[1])) / snap_tolerance_mm) * snap_tolerance_mm,
                    )
                    for point in points
                ]
                deduplicated = [local_points[0]]
                for point in local_points[1:]:
                    if point != deduplicated[-1]:
                        deduplicated.append(point)
                if len(deduplicated) < 2:
                    excluded_types["degenerate-after-snap"] += 1
                    continue
                if candidate.get("source_geometry_closed") is True and deduplicated[0] != deduplicated[-1]:
                    deduplicated.append(deduplicated[0])
                line = LineString(deduplicated)
                if line.is_empty or line.length == 0:
                    excluded_types["zero-length"] += 1
                    continue
                lines.append(line)
                source_candidate_ids.append(candidate["candidate_id"])

            polygons = []
            dangle_count = 0
            cut_count = 0
            invalid_count = 0
            if lines:
                noded = unary_union(lines)
                polygon_collection, cuts, dangles, invalid = polygonize_full(noded)
                polygons = [
                    polygon for polygon in polygon_collection.geoms
                    if polygon.area >= minimum_area_m2 * 1_000_000
                ]
                dangle_count = len(dangles.geoms)
                cut_count = len(cuts.geoms)
                invalid_count = len(invalid.geoms)

            category_items = []
            for polygon in sorted(polygons, key=lambda item: (item.bounds[0], item.bounds[1], item.area)):
                exterior = [
                    [round(x + float(origin[0]), 6), round(y + float(origin[1]), 6)]
                    for x, y in polygon.exterior.coords
                ]
                holes = [
                    [
                        [round(x + float(origin[0]), 6), round(y + float(origin[1]), 6)]
                        for x, y in ring.coords
                    ]
                    for ring in polygon.interiors
                ]
                digest_input = f"{plan_candidates['source_sha256']}:{category}:{polygon.wkb_hex}"
                item = {
                    "region_candidate_id": "cadregion-" + hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:24],
                    "category": category,
                    "area_m2": round(polygon.area / 1_000_000, 6),
                    "perimeter_m": round(polygon.length / 1_000, 6),
                    "bounds": {
                        "minimum": [round(polygon.bounds[0] + float(origin[0]), 6), round(polygon.bounds[1] + float(origin[1]), 6)],
                        "maximum": [round(polygon.bounds[2] + float(origin[0]), 6), round(polygon.bounds[3] + float(origin[1]), 6)],
                    },
                    "exterior_ring": exterior,
                    "interior_rings": holes,
                    "topology_status": "polygonized-candidate",
                    "secondary_cad_validation_status": "required",
                    "domain_object_status": "not-created",
                    "quantity_status": "not-ready",
                }
                items.append(item)
                category_items.append(item)

            category_summary.append({
                "category": category,
                "input_candidate_count": len(candidates),
                "linework_candidate_count": len(lines),
                "excluded_candidate_type_counts": dict(sorted(excluded_types.items())),
                "polygon_candidate_count": len(category_items),
                "polygon_candidate_total_area_m2": round(sum(item["area_m2"] for item in category_items), 6),
                "dangle_geometry_count": dangle_count,
                "cut_geometry_count": cut_count,
                "invalid_ring_geometry_count": invalid_count,
                "source_candidate_ids": sorted(source_candidate_ids),
            })
            total_line_count += len(lines)
            total_polygon_count += len(category_items)
            total_dangle_count += dangle_count
            total_cut_count += cut_count
            total_invalid_count += invalid_count

        return {
            "contract_version": "1.0",
            "source_asset_id": plan_candidates["source_asset_id"],
            "source_sha256": plan_candidates["source_sha256"],
            "plan_profile_id": plan_candidates["profile_id"],
            "status": "region-candidate-extraction-complete",
            "geometry_engine": {
                "name": "Shapely",
                "version": shapely.__version__,
                "geos_version": shapely.geos_version_string,
            },
            "policy": {
                "snap_tolerance_mm": snap_tolerance_mm,
                "minimum_area_m2": minimum_area_m2,
                "accepted_entity_types": sorted(LINEWORK_TYPES),
                "excluded_entity_types_are_reported": True,
            },
            "summary": {
                "linework_candidate_count": total_line_count,
                "polygon_candidate_count": total_polygon_count,
                "dangle_geometry_count": total_dangle_count,
                "cut_geometry_count": total_cut_count,
                "invalid_ring_geometry_count": total_invalid_count,
                "created_domain_object_count": 0,
                "quantity_ready_count": 0,
                "user_confirmation_required_now": False,
            },
            "category_summary": category_summary,
            "region_candidates": items,
            "warnings": [
                {
                    "code": "POLYGONIZED_REGIONS_ARE_NOT_ROOMS_OR_QUANTITIES",
                    "message": "Closed linework regions may be wall footprints, drafting subdivisions, or decoration boundaries and require category-specific and secondary CAD validation.",
                },
                {
                    "code": "HATCH_AND_DIMENSION_EVIDENCE_EXCLUDED",
                    "message": "Hatches and dimensions are reported but excluded from polygonization to avoid inventing boundary segments from parser-specific path ordering.",
                },
            ],
        }
