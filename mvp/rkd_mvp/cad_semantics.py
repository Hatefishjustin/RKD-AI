from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


REACHABLE_CONTEXTS = {
    "model-and-paper-reachable",
    "model-reachable",
    "paper-reachable",
}


class CadLayerSemanticMapper:
    """Maps CAD layer names to versioned domain categories without inventing geometry."""

    def __init__(self, rules: Mapping[str, Any]) -> None:
        self.rules = dict(rules)
        self._validate_rules()

    @classmethod
    def from_file(cls, path: str | Path) -> "CadLayerSemanticMapper":
        with Path(path).open("r", encoding="utf-8") as source:
            return cls(json.load(source))

    def map_inspection(self, inspection: Mapping[str, Any]) -> dict[str, Any]:
        if inspection.get("intake_status") != "geometry-parsed":
            raise ValueError("CAD semantic mapping requires a geometry-parsed inspection.")
        metadata = inspection.get("geometry_metadata")
        if not isinstance(metadata, Mapping):
            raise ValueError("CAD inspection has no geometry metadata.")
        layer_statistics = metadata.get("layer_statistics")
        if not isinstance(layer_statistics, list):
            raise ValueError("CAD inspection has no layer statistics.")

        mappings = [self._map_layer(layer) for layer in layer_statistics]
        aggregate: dict[str, dict[str, Any]] = {}
        disposition_counts: Counter[str] = Counter()
        review_layers: list[dict[str, Any]] = []
        mapped_entity_count = 0
        non_review_entity_count = 0
        reachable_entity_count = 0
        non_review_reachable_entity_count = 0
        unreachable_definition_entity_count = 0
        other_context_entity_count = 0

        for mapping in mappings:
            category = mapping["category"]
            summary = aggregate.setdefault(category, {
                "category": category,
                "layer_count": 0,
                "entity_count": 0,
                "reachable_entity_count": 0,
                "layer_names": [],
            })
            summary["layer_count"] += 1
            summary["entity_count"] += mapping["entity_count"]
            summary["reachable_entity_count"] += mapping["reachable_entity_count"]
            summary["layer_names"].append(mapping["layer_name"])
            disposition_counts[mapping["scope_disposition"]] += 1
            reachable_entity_count += mapping["reachable_entity_count"]
            unreachable_definition_entity_count += mapping["unreachable_definition_entity_count"]
            other_context_entity_count += mapping["other_context_entity_count"]
            if mapping["mapping_status"] == "mapped":
                mapped_entity_count += mapping["entity_count"]
                if mapping["verification_status"] != "needs-system-review":
                    non_review_entity_count += mapping["entity_count"]
                    non_review_reachable_entity_count += mapping["reachable_entity_count"]
            if mapping["verification_status"] == "needs-system-review":
                review_layers.append({
                    "layer_name": mapping["layer_name"],
                    "entity_count": mapping["entity_count"],
                    "reachable_entity_count": mapping["reachable_entity_count"],
                    "unreachable_definition_entity_count": mapping["unreachable_definition_entity_count"],
                    "top_entity_types": mapping["top_entity_types"],
                    "top_owner_blocks": mapping["top_owner_blocks"],
                    "reason": mapping["rationale"],
                })

        total_entities = int(metadata.get("entity_count", 0))
        review_layers.sort(key=lambda item: (-item["reachable_entity_count"], item["layer_name"]))
        mapped_layer_count = sum(item["mapping_status"] == "mapped" for item in mappings)
        professional_candidates = sum(
            item["entity_count"]
            for item in mappings
            if item["layer_role"] == "professional"
        )
        professional_reachable_candidates = sum(
            item["reachable_entity_count"]
            for item in mappings
            if item["layer_role"] == "professional"
        )
        review_reachable_entity_count = sum(
            item["reachable_entity_count"] for item in review_layers
        )
        warnings = [
            {
                "code": "BLOCK_INSTANCE_TRANSFORMS_NOT_APPLIED",
                "message": (
                    "Block reachability is evaluated, but insertion transforms and instance multiplication are "
                    "not applied yet. Entity counts are not quantities of real-world objects."
                ),
            }
        ]
        if review_layers:
            warnings.append({
                "code": "LAYERS_REQUIRE_SYSTEM_REVIEW",
                "message": (
                    f"{len(review_layers)} layer candidates require system review of block and layout "
                    "context before requesting user confirmation."
                ),
            })
        if metadata.get("requires_secondary_validation"):
            warnings.append({
                "code": "SOURCE_GEOMETRY_REQUIRES_SECONDARY_VALIDATION",
                "message": "Source parser diagnostics require a second-engine or original-CAD spot check.",
            })

        return {
            "contract_version": "1.0",
            "mapping_version": self.rules["mapping_version"],
            "source_asset_id": inspection.get("source_asset_id"),
            "source_sha256": inspection.get("sha256"),
            "source_geometry_quality": metadata.get("quality_status"),
            "mapping_status": "mapped-with-review-items" if review_layers else "mapped",
            "summary": {
                "total_layer_count": len(mappings),
                "mapped_layer_count": mapped_layer_count,
                "review_layer_count": len(review_layers),
                "total_entity_count": total_entities,
                "mapped_storage_entity_count": mapped_entity_count,
                "mapped_storage_entity_ratio": round(mapped_entity_count / total_entities, 6) if total_entities else 0.0,
                "non_review_storage_entity_count": non_review_entity_count,
                "non_review_storage_entity_ratio": round(non_review_entity_count / total_entities, 6) if total_entities else 0.0,
                "review_storage_entity_count": total_entities - non_review_entity_count,
                "professional_candidate_storage_entity_count": professional_candidates,
                "reachable_entity_count": reachable_entity_count,
                "reachable_entity_ratio": round(reachable_entity_count / total_entities, 6) if total_entities else 0.0,
                "unreachable_definition_entity_count": unreachable_definition_entity_count,
                "other_context_entity_count": other_context_entity_count,
                "non_review_reachable_entity_count": non_review_reachable_entity_count,
                "review_reachable_entity_count": review_reachable_entity_count,
                "professional_candidate_reachable_entity_count": professional_reachable_candidates,
                "scope_disposition_layer_counts": dict(sorted(disposition_counts.items())),
                "user_confirmation_required_now": False,
            },
            "category_summary": sorted(aggregate.values(), key=lambda item: item["category"]),
            "layer_mappings": mappings,
            "system_review_queue": review_layers,
            "warnings": warnings,
        }

    def _map_layer(self, layer: Mapping[str, Any]) -> dict[str, Any]:
        name = layer.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Layer statistics contain an invalid name.")
        rule = self._find_rule(name)
        entity_counts = layer.get("entity_counts")
        if not isinstance(entity_counts, Mapping):
            raise ValueError(f"Layer {name!r} has invalid entity counts.")
        context_counts = layer.get("block_context_counts")
        if not isinstance(context_counts, Mapping):
            raise ValueError(f"Layer {name!r} has no block context counts.")
        entity_count = int(layer.get("entity_count", 0))
        if sum(context_counts.values()) != entity_count:
            raise ValueError(f"Layer {name!r} block context counts do not match its entity count.")
        reachable_entity_count = sum(context_counts.get(context, 0) for context in REACHABLE_CONTEXTS)
        unreachable_definition_entity_count = int(context_counts.get("unreachable-block-definition", 0))
        other_context_entity_count = entity_count - reachable_entity_count - unreachable_definition_entity_count
        top_owner_blocks = layer.get("top_owner_blocks")
        if not isinstance(top_owner_blocks, list):
            raise ValueError(f"Layer {name!r} has no owner block summary.")
        top_entity_types = [
            {"entity_type": entity_type, "count": count}
            for entity_type, count in list(entity_counts.items())[:5]
        ]
        if rule is None:
            return {
                "layer_name": name,
                "layer_handle": layer.get("handle"),
                "entity_count": entity_count,
                "reachable_entity_count": reachable_entity_count,
                "unreachable_definition_entity_count": unreachable_definition_entity_count,
                "other_context_entity_count": other_context_entity_count,
                "block_context_counts": dict(context_counts),
                "top_owner_blocks": top_owner_blocks,
                "top_entity_types": top_entity_types,
                "mapping_status": "unclassified",
                "category": "cad.unclassified",
                "layer_role": "review",
                "confidence": 0.0,
                "rule_id": None,
                "verification_status": "needs-system-review",
                "scope_disposition": "undetermined",
                "rationale": "No approved exact or pattern rule matches this layer name.",
            }
        return {
            "layer_name": name,
            "layer_handle": layer.get("handle"),
            "entity_count": entity_count,
            "reachable_entity_count": reachable_entity_count,
            "unreachable_definition_entity_count": unreachable_definition_entity_count,
            "other_context_entity_count": other_context_entity_count,
            "block_context_counts": dict(context_counts),
            "top_owner_blocks": top_owner_blocks,
            "top_entity_types": top_entity_types,
            "mapping_status": "mapped",
            "category": rule["category"],
            "layer_role": rule["layer_role"],
            "confidence": rule["confidence"],
            "rule_id": rule["rule_id"],
            "verification_status": rule["verification_status"],
            "scope_disposition": rule["scope_disposition"],
            "rationale": rule["rationale"],
        }

    def _find_rule(self, layer_name: str) -> Mapping[str, Any] | None:
        for rule in self.rules["rules"]:
            exact_names = rule.get("exact_names", [])
            if layer_name in exact_names:
                return rule
            pattern = rule.get("pattern")
            if pattern and re.search(pattern, layer_name, re.IGNORECASE):
                return rule
        return None

    def _validate_rules(self) -> None:
        if self.rules.get("contract_version") != "1.0":
            raise ValueError("Unsupported CAD semantic rule contract version.")
        if not isinstance(self.rules.get("mapping_version"), str) or not self.rules["mapping_version"]:
            raise ValueError("CAD semantic rules require a mapping_version.")
        rules = self.rules.get("rules")
        if not isinstance(rules, list) or not rules:
            raise ValueError("CAD semantic rules require a non-empty rules list.")
        rule_ids: set[str] = set()
        exact_names: set[str] = set()
        for rule in rules:
            required = {
                "rule_id", "category", "layer_role", "confidence",
                "verification_status", "scope_disposition", "rationale",
            }
            missing = required.difference(rule)
            if missing:
                raise ValueError(f"CAD semantic rule is missing fields: {', '.join(sorted(missing))}")
            rule_id = rule["rule_id"]
            if rule_id in rule_ids:
                raise ValueError(f"Duplicate CAD semantic rule id: {rule_id}")
            rule_ids.add(rule_id)
            if not rule.get("exact_names") and not rule.get("pattern"):
                raise ValueError(f"Rule {rule_id} needs exact_names or pattern.")
            for name in rule.get("exact_names", []):
                if name in exact_names:
                    raise ValueError(f"Layer name {name!r} appears in multiple exact rules.")
                exact_names.add(name)
            confidence = rule["confidence"]
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError(f"Rule {rule_id} confidence must be between 0 and 1.")
