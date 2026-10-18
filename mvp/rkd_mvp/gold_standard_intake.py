from __future__ import annotations

import hashlib
import mimetypes
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


ROLES = {
    "requirements",
    "survey",
    "cad",
    "model",
    "render",
    "construction-drawing",
    "materials",
    "quotation",
    "change",
    "approval-evidence",
    "completion-photo",
    "unclassified",
}

RECOMMENDED_ROLES = [
    "requirements",
    "survey",
    "cad",
    "model",
    "render",
    "construction-drawing",
    "materials",
    "quotation",
    "change",
    "approval-evidence",
    "completion-photo",
]

MEDIA_TYPES = {
    ".dwg": "image/vnd.dwg",
    ".dxf": "image/vnd.dxf",
    ".rvt": "application/vnd.autodesk.revit",
    ".ifc": "application/x-step",
    ".skp": "application/vnd.sketchup.skp",
    ".3dm": "model/vnd.rhino",
    ".max": "application/x-3ds-max",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class GoldStandardInventoryBuilder:
    """Builds a deterministic, read-only inventory for a historical project package."""

    def build(self, source_directory: str | Path, config: Mapping[str, Any]) -> dict[str, Any]:
        root = Path(source_directory).resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        normalized = self._validate_config(config)
        overrides = normalized.get("asset_overrides", {})
        assets: list[dict[str, Any]] = []
        skipped_symlinks: list[str] = []

        paths = sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold())
        for path in paths:
            if path.is_symlink():
                skipped_symlinks.append(path.relative_to(root).as_posix())
                continue
            if not path.is_file():
                continue
            relative_path = path.relative_to(root).as_posix()
            override = overrides.get(relative_path, {})
            assets.append(self._asset(root, path, relative_path, normalized, override))

        asset_by_path = {item["relative_path"]: item for item in assets}
        relationships = self._relationships(normalized.get("version_relationships", []), asset_by_path)
        duplicate_groups = self._mark_duplicates(assets)
        coverage = self._coverage(assets, normalized)
        intake_status = self._intake_status(normalized, coverage)
        warnings = [
            {
                "code": "INGESTION_IS_NOT_TRAINING_AUTHORIZATION",
                "message": "Registering project files does not grant model-training rights; only the explicit permission record applies.",
            },
            {
                "code": "PROFESSIONAL_GROUND_TRUTH_REQUIRED",
                "message": "Candidate roles and file hashes are not professional approval of correctness, tolerances, or known defects.",
            },
        ]
        if coverage["missing_recommended_roles"]:
            warnings.append({
                "code": "RECOMMENDED_COVERAGE_INCOMPLETE",
                "message": "Missing recommended roles: " + ", ".join(coverage["missing_recommended_roles"]),
            })
        if self._professional_defects_block(normalized["professional_review"]):
            warnings.append({
                "code": "PROFESSIONAL_DEFECTS_BLOCK_REPLAY",
                "message": "Unaccepted or E0/E1 known defects prevent this package from becoming a positive replay gold standard.",
            })
        if skipped_symlinks:
            warnings.append({
                "code": "SYMLINKS_SKIPPED",
                "message": f"Skipped {len(skipped_symlinks)} symbolic links to keep the inventory inside the declared source root.",
            })

        return {
            "contract_version": "1.0",
            "dataset_id": normalized["dataset_id"],
            "organization_id": normalized["organization_id"],
            "source_project_ref": normalized["source_project_ref"],
            "project_type": normalized["project_type"],
            "source_root_name": root.name,
            "received_at": normalized["received_at"],
            "use_permissions": normalized["use_permissions"],
            "privacy": normalized["privacy"],
            "intake_status": intake_status,
            "assets": assets,
            "version_relationships": relationships,
            "duplicate_groups": duplicate_groups,
            "coverage": coverage,
            "professional_review": normalized["professional_review"],
            "warnings": warnings,
        }

    @staticmethod
    def _validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
        required = {
            "dataset_id", "organization_id", "source_project_ref", "project_type", "received_at",
            "use_permissions", "privacy", "professional_review",
        }
        missing = sorted(required.difference(config))
        if missing:
            raise ValueError(f"Gold-standard intake config is missing: {', '.join(missing)}")
        normalized = dict(config)
        if config.get("project_type") not in {
            "enterprise-space", "office", "retail", "hospitality", "residential", "mixed", "unknown",
        }:
            raise ValueError("Unsupported historical project type.")
        permissions = config.get("use_permissions")
        if not isinstance(permissions, Mapping):
            raise ValueError("use_permissions must be an object.")
        for purpose in ("evaluation", "training", "external_model_upload"):
            permission = permissions.get(purpose)
            if not isinstance(permission, Mapping):
                raise ValueError(f"Missing use permission: {purpose}")
            status = permission.get("status")
            reference = permission.get("authorization_reference")
            if status not in {"authorized", "pending", "prohibited"}:
                raise ValueError(f"Invalid {purpose} permission status.")
            if status == "authorized" and not isinstance(reference, str):
                raise ValueError(f"Authorized {purpose} use requires an authorization reference.")
            if status == "authorized" and not reference.strip():
                raise ValueError(f"Authorized {purpose} use requires a non-empty authorization reference.")
        privacy = config.get("privacy")
        if not isinstance(privacy, Mapping) or privacy.get("classification") not in {
            "public", "internal", "confidential", "restricted",
        }:
            raise ValueError("A valid privacy classification is required.")
        privacy_required = {
            "classification", "contains_personal_data", "contains_client_identifiers",
            "deidentification_status", "review_status",
        }
        if privacy_required.difference(privacy):
            raise ValueError("Privacy review fields are incomplete.")
        if privacy.get("deidentification_status") not in {
            "not-started", "in-progress", "completed", "not-required",
        } or privacy.get("review_status") not in {"pending", "approved", "rejected"}:
            raise ValueError("Privacy review statuses are invalid.")
        if not isinstance(privacy.get("contains_personal_data"), bool) or not isinstance(
            privacy.get("contains_client_identifiers"), bool
        ):
            raise ValueError("Privacy data flags must be boolean.")
        professional_review = config.get("professional_review")
        if not isinstance(professional_review, Mapping) or professional_review.get("status") not in {
            "unassigned", "pending", "approved", "rejected",
        }:
            raise ValueError("A valid professional_review status is required.")
        review_required = {
            "status", "reviewer_role", "reviewed_at", "approval_reference",
            "tolerance_profile_id", "known_defects",
        }
        if review_required.difference(professional_review) or not isinstance(
            professional_review.get("known_defects"), list
        ):
            raise ValueError("Professional review fields are incomplete.")
        for defect in professional_review["known_defects"]:
            if not isinstance(defect, Mapping) or {
                "defect_id", "severity", "description", "accepted_for_replay",
            }.difference(defect):
                raise ValueError("Known defect records are incomplete.")
            if defect["severity"] not in {"E0", "E1", "E2", "E3"} or not isinstance(
                defect["accepted_for_replay"], bool
            ):
                raise ValueError("Known defect severity or replay decision is invalid.")
        if professional_review["status"] == "approved":
            approval_fields = ("reviewer_role", "reviewed_at", "approval_reference", "tolerance_profile_id")
            if any(not isinstance(professional_review.get(field), str) or not professional_review[field].strip() for field in approval_fields):
                raise ValueError("Approved professional review requires reviewer, time, approval, and tolerance references.")
        received_at = config.get("received_at")
        if not isinstance(received_at, str):
            raise ValueError("received_at must be an ISO 8601 date-time string.")
        try:
            datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("received_at must be an ISO 8601 date-time string.") from error
        overrides = config.get("asset_overrides", {})
        if not isinstance(overrides, Mapping):
            raise ValueError("asset_overrides must be an object keyed by relative path.")
        normalized_overrides: dict[str, dict[str, Any]] = {}
        for raw_path, override in overrides.items():
            normalized_path = GoldStandardInventoryBuilder._validate_relative_path(raw_path)
            if not isinstance(override, Mapping):
                raise ValueError(f"Asset override for {raw_path!r} must be an object.")
            role = override.get("role")
            if role is not None and role not in ROLES:
                raise ValueError(f"Unsupported asset role for {raw_path!r}: {role}")
            privacy_classification = override.get("privacy_classification")
            if privacy_classification is not None and privacy_classification not in {
                "public", "internal", "confidential", "restricted",
            }:
                raise ValueError(f"Invalid privacy classification for {raw_path!r}.")
            normalized_overrides[normalized_path] = dict(override)
        normalized["asset_overrides"] = normalized_overrides
        return normalized

    @staticmethod
    def _validate_relative_path(value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("Asset paths must be non-empty strings.")
        normalized = value.replace("\\", "/")
        candidate = PurePosixPath(normalized)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Asset path must stay inside the source root: {value!r}")
        return normalized

    def _asset(
        self,
        root: Path,
        path: Path,
        relative_path: str,
        config: Mapping[str, Any],
        override: Mapping[str, Any],
    ) -> dict[str, Any]:
        digest = hashlib.sha256()
        size_bytes = 0
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size_bytes += len(chunk)
        sha256 = digest.hexdigest().upper()
        inferred_role = self._infer_role(relative_path)
        role = override.get("role", inferred_role)
        role_status = override.get("role_status")
        if role_status is None:
            role_status = "confirmed" if "role" in override else (
                "unclassified" if role == "unclassified" else "candidate"
            )
        if role_status not in {"candidate", "confirmed", "unclassified"}:
            raise ValueError(f"Invalid role_status for {relative_path!r}.")
        privacy = config["privacy"]
        deidentification_status = override.get("deidentification_status")
        if deidentification_status is None:
            if privacy.get("deidentification_status") == "completed":
                deidentification_status = "completed"
            elif privacy.get("deidentification_status") == "not-required":
                deidentification_status = "not-required"
            else:
                deidentification_status = "unreviewed"
        if deidentification_status not in {"unreviewed", "required", "completed", "not-required"}:
            raise ValueError(f"Invalid deidentification status for {relative_path!r}.")
        suffix = path.suffix.casefold()
        media_type = MEDIA_TYPES.get(suffix) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        asset_key = f"{config['dataset_id']}:{relative_path}"
        return {
            "asset_id": "gsasset-" + hashlib.sha256(asset_key.encode("utf-8")).hexdigest()[:24],
            "relative_path": relative_path,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "media_type": media_type,
            "source_class": "source",
            "ingestion_mode": "read-only",
            "candidate_role": role,
            "role_status": role_status,
            "revision_id": override.get("revision_id"),
            "privacy_classification": override.get("privacy_classification", privacy["classification"]),
            "deidentification_status": deidentification_status,
            "duplicate_of": None,
        }

    @staticmethod
    def _infer_role(relative_path: str) -> str:
        name = relative_path.casefold()
        suffix = Path(relative_path).suffix.casefold()
        if any(token in name for token in ("施工图", "竣工图", "construction")):
            return "construction-drawing"
        if any(token in name for token in ("完工", "竣工照片", "completion", "as-built-photo")):
            return "completion-photo"
        if any(token in name for token in ("变更", "签证", "change-order", "variation")):
            return "change"
        if any(token in name for token in ("审批", "确认", "approval", "signoff")):
            return "approval-evidence"
        if any(token in name for token in ("报价", "预算", "quote", "quotation", "boq")):
            return "quotation"
        if any(token in name for token in ("材料", "material", "样板")):
            return "materials"
        if any(token in name for token in ("效果图", "render", "visualization")):
            return "render"
        if any(token in name for token in ("需求", "任务书", "brief", "requirement")):
            return "requirements"
        if any(token in name for token in ("量房", "测量", "survey", "原始图")):
            return "survey"
        if suffix in {".rvt", ".ifc", ".skp", ".3dm", ".max"}:
            return "model"
        if suffix in {".dwg", ".dxf"}:
            return "cad"
        return "unclassified"

    def _relationships(
        self,
        records: Any,
        asset_by_path: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(records, list):
            raise ValueError("version_relationships must be an array.")
        relationships: list[dict[str, Any]] = []
        allowed = {"supersedes", "derived-from", "corresponds-to", "approves", "documents-change-to"}
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError("Each version relationship must be an object.")
            from_path = self._validate_relative_path(record.get("from_path"))
            to_path = self._validate_relative_path(record.get("to_path"))
            if from_path not in asset_by_path or to_path not in asset_by_path:
                raise ValueError(f"Relationship references an unknown asset: {from_path!r} -> {to_path!r}")
            relationship_type = record.get("relationship_type")
            status = record.get("status", "candidate")
            if relationship_type not in allowed or status not in {"candidate", "confirmed"}:
                raise ValueError("Invalid relationship type or status.")
            relationships.append({
                "from_asset_id": asset_by_path[from_path]["asset_id"],
                "to_asset_id": asset_by_path[to_path]["asset_id"],
                "relationship_type": relationship_type,
                "status": status,
            })
        return relationships

    @staticmethod
    def _mark_duplicates(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for asset in assets:
            by_hash[asset["sha256"]].append(asset)
        groups: list[dict[str, Any]] = []
        for sha256, matches in sorted(by_hash.items()):
            if len(matches) < 2:
                continue
            canonical = matches[0]["asset_id"]
            for duplicate in matches[1:]:
                duplicate["duplicate_of"] = canonical
            groups.append({"sha256": sha256, "asset_ids": [item["asset_id"] for item in matches]})
        return groups

    @staticmethod
    def _coverage(assets: list[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
        confirmed = Counter(
            asset["candidate_role"] for asset in assets if asset["role_status"] == "confirmed"
        )
        candidates = Counter(
            asset["candidate_role"] for asset in assets if asset["role_status"] == "candidate"
        )
        present = set(confirmed) | set(candidates)
        missing = [role for role in RECOMMENDED_ROLES if role not in present]
        ready = (
            not missing
            and config["use_permissions"]["evaluation"]["status"] == "authorized"
            and config["privacy"]["review_status"] == "approved"
            and config["professional_review"]["status"] == "approved"
            and not GoldStandardInventoryBuilder._professional_defects_block(config["professional_review"])
        )
        if ready:
            replay_readiness = "ready"
        elif config["use_permissions"]["evaluation"]["status"] == "prohibited":
            replay_readiness = "blocked"
        else:
            replay_readiness = "pending-review"
        return {
            "asset_count": len(assets),
            "total_size_bytes": sum(int(asset["size_bytes"]) for asset in assets),
            "confirmed_role_counts": dict(sorted(confirmed.items())),
            "candidate_role_counts": dict(sorted(candidates.items())),
            "recommended_roles": RECOMMENDED_ROLES,
            "missing_recommended_roles": missing,
            "replay_readiness": replay_readiness,
        }

    @staticmethod
    def _intake_status(config: Mapping[str, Any], coverage: Mapping[str, Any]) -> str:
        if config["use_permissions"]["evaluation"]["status"] == "prohibited":
            return "blocked"
        privacy = config["privacy"]
        if privacy["review_status"] == "rejected":
            return "blocked"
        if privacy["review_status"] != "approved" or privacy["deidentification_status"] in {"not-started", "in-progress"}:
            return "privacy-review-required"
        review = config["professional_review"]
        if review["status"] == "rejected":
            return "blocked"
        if GoldStandardInventoryBuilder._professional_defects_block(review):
            return "blocked"
        if review["status"] != "approved":
            return "professional-review-required"
        return "ready-for-replay" if coverage["replay_readiness"] == "ready" else "inventory-created"

    @staticmethod
    def _professional_defects_block(review: Mapping[str, Any]) -> bool:
        return any(
            defect.get("severity") in {"E0", "E1"}
            or defect.get("accepted_for_replay") is not True
            for defect in review.get("known_defects", [])
            if isinstance(defect, Mapping)
        )
