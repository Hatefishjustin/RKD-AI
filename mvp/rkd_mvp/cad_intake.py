from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


DWG_VERSIONS = {
    "AC1015": "AutoCAD 2000/2000i/2002",
    "AC1018": "AutoCAD 2004/2005/2006",
    "AC1021": "AutoCAD 2007/2008/2009",
    "AC1024": "AutoCAD 2010/2011/2012",
    "AC1027": "AutoCAD 2013-2017",
    "AC1032": "AutoCAD 2018-2026",
}

DWG_UNITS = {
    0: "unitless",
    1: "inches",
    2: "feet",
    3: "miles",
    4: "millimeters",
    5: "centimeters",
    6: "meters",
    7: "kilometers",
    8: "microinches",
    9: "mils",
    10: "yards",
    11: "angstroms",
    12: "nanometers",
    13: "microns",
    14: "decimeters",
    15: "decameters",
    16: "hectometers",
    17: "gigameters",
    18: "astronomical-units",
    19: "light-years",
    20: "parsecs",
}


class CadGeometryParser(Protocol):
    name: str
    version: str

    def supports(self, dwg_signature: str) -> bool: ...

    def parse(self, source_path: Path) -> Mapping[str, Any]: ...


class LibreDwgParser:
    """Runs a local LibreDWG binary and returns a compact, validated summary."""

    name = "GNU LibreDWG"

    def __init__(self, tool_directory: str | Path, timeout_seconds: int = 180) -> None:
        self.tool_directory = Path(tool_directory).resolve()
        self.dwgread = self.tool_directory / "dwgread.exe"
        self.dwglayers = self.tool_directory / "dwglayers.exe"
        self.timeout_seconds = timeout_seconds
        for executable in (self.dwgread, self.dwglayers):
            if not executable.is_file():
                raise FileNotFoundError(executable)
        self.version = self._detect_version()

    def supports(self, dwg_signature: str) -> bool:
        return dwg_signature in DWG_VERSIONS

    def parse(self, source_path: Path) -> Mapping[str, Any]:
        source = source_path.resolve()
        with tempfile.TemporaryDirectory(prefix="rkd-libredwg-") as temporary_directory:
            temporary = Path(temporary_directory)
            payload, json_size_bytes, diagnostics_path = self._read_payload(source, temporary)
            layer_output_path = temporary / "layers.txt"
            layer_diagnostics_path = temporary / "dwglayers-diagnostics.log"

            with layer_output_path.open("wb") as layer_output, layer_diagnostics_path.open("wb") as layer_diagnostics:
                layer_result = subprocess.run(
                    [str(self.dwglayers), "-f", str(source)],
                    cwd=self.tool_directory,
                    stdout=layer_output,
                    stderr=layer_diagnostics,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            if layer_result.returncode != 0:
                detail = self._diagnostic_tail(layer_diagnostics_path)
                raise RuntimeError(f"dwglayers exited with {layer_result.returncode}: {detail}")

            layer_names = self._parse_layer_names(layer_output_path.read_bytes())
            diagnostics = self._summarize_diagnostics(diagnostics_path)
            return self._summarize_payload(
                payload,
                layer_names,
                json_size_bytes,
                diagnostics,
            )

    def load_payload(self, source_path: str | Path) -> Mapping[str, Any]:
        """Loads validated minJSON for a bounded downstream analyzer without persisting it."""
        source = Path(source_path).resolve()
        with tempfile.TemporaryDirectory(prefix="rkd-libredwg-payload-") as temporary_directory:
            payload, _, _ = self._read_payload(source, Path(temporary_directory))
            return payload

    def _read_payload(
        self,
        source: Path,
        temporary: Path,
    ) -> tuple[dict[str, Any], int, Path]:
        json_path = temporary / "drawing.min.json"
        diagnostics_path = temporary / "dwgread-diagnostics.log"
        with diagnostics_path.open("wb") as diagnostics:
            result = subprocess.run(
                [
                    str(self.dwgread),
                    "-v1",
                    "-O",
                    "minJSON",
                    "-o",
                    str(json_path),
                    str(source),
                ],
                cwd=self.tool_directory,
                stdout=subprocess.DEVNULL,
                stderr=diagnostics,
                timeout=self.timeout_seconds,
                check=False,
            )
        if result.returncode != 0:
            detail = self._diagnostic_tail(diagnostics_path)
            raise RuntimeError(f"dwgread exited with {result.returncode}: {detail}")
        if not json_path.is_file() or json_path.stat().st_size == 0:
            raise RuntimeError("dwgread returned success without a JSON output file.")
        try:
            with json_path.open("r", encoding="utf-8") as source_json:
                payload = json.load(source_json)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"dwgread returned incomplete or invalid JSON: {error}") from error
        self._validate_payload(payload)
        return payload, json_path.stat().st_size, diagnostics_path

    def _detect_version(self) -> str:
        result = subprocess.run(
            [str(self.dwgread), "--version"],
            cwd=self.tool_directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            check=False,
        )
        text = self._decode(result.stdout).strip()
        match = re.search(r"dwgread\s+([^\s]+)", text, re.IGNORECASE)
        if result.returncode != 0 or match is None:
            raise RuntimeError(f"Unable to identify dwgread version: {text or '<no output>'}")
        return match.group(1)

    @staticmethod
    def _validate_payload(payload: Any) -> None:
        if not isinstance(payload, dict):
            raise RuntimeError("dwgread JSON root must be an object.")
        required_sections = ("FILEHEADER", "HEADER", "OBJECTS")
        missing = [section for section in required_sections if section not in payload]
        if missing:
            raise RuntimeError(f"dwgread JSON is missing required sections: {', '.join(missing)}")
        if not isinstance(payload["HEADER"], dict) or not isinstance(payload["OBJECTS"], list):
            raise RuntimeError("dwgread JSON contains invalid HEADER or OBJECTS sections.")

    @classmethod
    def _summarize_payload(
        cls,
        payload: Mapping[str, Any],
        layer_names: list[str],
        json_size_bytes: int,
        diagnostics: Mapping[str, Any],
    ) -> dict[str, Any]:
        objects = payload["OBJECTS"]
        entity_counts = Counter(
            str(item["entity"])
            for item in objects
            if isinstance(item, dict) and item.get("entity")
        )
        object_counts = Counter(
            str(item["object"])
            for item in objects
            if isinstance(item, dict) and item.get("object")
        )
        header = payload["HEADER"]
        unit_code = header.get("INSUNITS")
        diagnostic_count = int(diagnostics.get("diagnostic_line_count", 0))
        quality_status = "parsed-with-compatibility-warnings" if diagnostic_count else "parsed"
        dimension_count = sum(
            count for name, count in entity_counts.items() if name.startswith("DIMENSION_")
        )
        text_count = sum(
            entity_counts.get(name, 0) for name in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF")
        )
        layer_statistics, unresolved_layer_reference_count = cls._build_layer_statistics(
            objects,
            layer_names,
        )
        block_context = cls._attach_block_context(objects, layer_statistics)
        return {
            "quality_status": quality_status,
            "requires_secondary_validation": diagnostic_count > 0,
            "parser_output_validation": {
                "valid_json": True,
                "required_sections_present": True,
                "json_size_bytes": json_size_bytes,
            },
            "drawing_units": {
                "code": unit_code,
                "name": DWG_UNITS.get(unit_code, "unknown"),
            },
            "object_count": len(objects),
            "entity_count": sum(entity_counts.values()),
            "non_entity_object_count": sum(object_counts.values()),
            "entity_type_count": len(entity_counts),
            "entity_counts": dict(sorted(entity_counts.items(), key=lambda item: (-item[1], item[0]))),
            "text_entity_count": text_count,
            "dimension_entity_count": dimension_count,
            "layer_count": len(layer_names),
            "layer_names": layer_names,
            "layer_statistics": layer_statistics,
            "unresolved_layer_reference_count": unresolved_layer_reference_count,
            "block_context": block_context,
            "global_extents": {
                "minimum": header.get("EXTMIN"),
                "maximum": header.get("EXTMAX"),
                "usage": "diagnostic-only; includes the complete drawing set and layouts",
            },
            "parser_diagnostics": dict(diagnostics),
        }

    @staticmethod
    def _build_layer_statistics(
        objects: list[Mapping[str, Any]],
        layer_names: list[str],
    ) -> tuple[list[dict[str, Any]], int]:
        layer_objects = [
            item for item in objects
            if isinstance(item, dict) and item.get("object") == "LAYER"
        ]
        if len(layer_objects) != len(layer_names):
            raise RuntimeError(
                f"Layer object/name count mismatch: {len(layer_objects)} objects, {len(layer_names)} names."
            )

        handle_to_name: dict[int, str] = {}
        handles_by_name: dict[str, int] = {}
        for layer_object, layer_name in zip(layer_objects, layer_names):
            raw_name = str(layer_object.get("name", ""))
            if raw_name.isascii() and "\ufffd" not in raw_name and raw_name != layer_name:
                raise RuntimeError(
                    f"Layer order validation failed: JSON name {raw_name!r}, layer list name {layer_name!r}."
                )
            handle = layer_object.get("handle")
            if not isinstance(handle, list) or not handle or not isinstance(handle[-1], int):
                raise RuntimeError(f"Layer {layer_name!r} has no usable handle.")
            handle_value = handle[-1]
            if handle_value in handle_to_name:
                raise RuntimeError(f"Duplicate layer handle: {handle_value}.")
            handle_to_name[handle_value] = layer_name
            handles_by_name[layer_name] = handle_value

        counts_by_name = {name: Counter() for name in layer_names}
        unresolved_layer_reference_count = 0
        for item in objects:
            if not isinstance(item, dict) or not item.get("entity"):
                continue
            layer_reference = item.get("layer")
            if not isinstance(layer_reference, list) or not layer_reference:
                unresolved_layer_reference_count += 1
                continue
            layer_name = handle_to_name.get(layer_reference[-1])
            if layer_name is None:
                unresolved_layer_reference_count += 1
                continue
            counts_by_name[layer_name][str(item["entity"])] += 1

        statistics = []
        for name in layer_names:
            counts = counts_by_name[name]
            statistics.append({
                "name": name,
                "handle": handles_by_name[name],
                "entity_count": sum(counts.values()),
                "entity_counts": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
            })
        return statistics, unresolved_layer_reference_count

    @classmethod
    def _attach_block_context(
        cls,
        objects: list[Mapping[str, Any]],
        layer_statistics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        block_headers = {
            handle: item
            for item in objects
            if isinstance(item, dict) and item.get("object") == "BLOCK_HEADER"
            if (handle := cls._last_handle(item.get("handle"))) is not None
        }
        entity_owner: dict[int, int] = {}
        for block_handle, block_header in block_headers.items():
            for entity_reference in block_header.get("entities", []) or []:
                entity_handle = cls._last_handle(entity_reference)
                if entity_handle is not None:
                    entity_owner[entity_handle] = block_handle

        block_graph: dict[int, set[int]] = {}
        insertion_reference_counts: Counter[int] = Counter()
        insert_relationship_count = 0
        for item in objects:
            if not isinstance(item, dict) or item.get("entity") != "INSERT":
                continue
            owner = cls._entity_owner_handle(item, entity_owner, block_headers)
            target = cls._last_handle(item.get("block_header"))
            if owner not in block_headers or target not in block_headers:
                continue
            block_graph.setdefault(owner, set()).add(target)
            insertion_reference_counts[target] += 1
            insert_relationship_count += 1

        model_roots = [
            handle for handle, item in block_headers.items()
            if item.get("name") == "*Model_Space"
        ]
        paper_roots = [
            handle for handle, item in block_headers.items()
            if str(item.get("name", "")).startswith("*Paper_Space")
        ]
        model_reachable = cls._reachable_blocks(model_roots, block_graph)
        paper_reachable = cls._reachable_blocks(paper_roots, block_graph)

        layer_by_handle = {item["handle"]: item for item in layer_statistics}
        context_counts_by_layer = {
            item["name"]: Counter() for item in layer_statistics
        }
        owners_by_layer: dict[str, Counter[int | None]] = {
            item["name"]: Counter() for item in layer_statistics
        }
        total_context_counts: Counter[str] = Counter()
        for item in objects:
            if not isinstance(item, dict) or not item.get("entity"):
                continue
            layer_handle = cls._last_handle(item.get("layer"))
            layer = layer_by_handle.get(layer_handle)
            if layer is None:
                continue
            owner = cls._entity_owner_handle(item, entity_owner, block_headers)
            context = cls._owner_context(owner, block_headers, model_reachable, paper_reachable)
            context_counts_by_layer[layer["name"]][context] += 1
            owners_by_layer[layer["name"]][owner] += 1
            total_context_counts[context] += 1

        for layer in layer_statistics:
            name = layer["name"]
            context_counts = context_counts_by_layer[name]
            layer["block_context_counts"] = dict(sorted(context_counts.items()))
            top_owner_blocks = []
            for owner, entity_count in owners_by_layer[name].most_common(8):
                block_header = block_headers.get(owner, {})
                top_owner_blocks.append({
                    "block_handle": owner,
                    "block_name": block_header.get("name") if owner is not None else None,
                    "entity_count": entity_count,
                    "context": cls._owner_context(
                        owner,
                        block_headers,
                        model_reachable,
                        paper_reachable,
                    ),
                    "insertion_reference_count": insertion_reference_counts.get(owner, 0),
                    "external_reference_hint": bool(
                        block_header.get("blkisxref") or block_header.get("xref_pname")
                    ),
                })
            layer["top_owner_blocks"] = top_owner_blocks

        return {
            "block_header_count": len(block_headers),
            "insert_relationship_count": insert_relationship_count,
            "unique_block_graph_edge_count": sum(len(targets) for targets in block_graph.values()),
            "model_space_root_count": len(model_roots),
            "paper_space_root_count": len(paper_roots),
            "model_reachable_block_count": len(model_reachable),
            "paper_reachable_block_count": len(paper_reachable),
            "model_and_paper_reachable_block_count": len(model_reachable & paper_reachable),
            "entity_context_counts": dict(sorted(total_context_counts.items())),
        }

    @staticmethod
    def _last_handle(value: Any) -> int | None:
        if isinstance(value, list) and value and isinstance(value[-1], int):
            return value[-1]
        return None

    @classmethod
    def _entity_owner_handle(
        cls,
        entity: Mapping[str, Any],
        entity_owner: Mapping[int, int],
        block_headers: Mapping[int, Mapping[str, Any]],
    ) -> int | None:
        entity_handle = cls._last_handle(entity.get("handle"))
        if entity_handle is not None and entity_handle in entity_owner:
            return entity_owner[entity_handle]
        owner = cls._last_handle(entity.get("ownerhandle"))
        return owner if owner in block_headers else None

    @staticmethod
    def _reachable_blocks(roots: list[int], graph: Mapping[int, set[int]]) -> set[int]:
        reachable = set(roots)
        pending = list(roots)
        while pending:
            for target in graph.get(pending.pop(), set()):
                if target not in reachable:
                    reachable.add(target)
                    pending.append(target)
        return reachable

    @staticmethod
    def _owner_context(
        owner: int | None,
        block_headers: Mapping[int, Mapping[str, Any]],
        model_reachable: set[int],
        paper_reachable: set[int],
    ) -> str:
        if owner is None:
            return "unowned"
        in_model = owner in model_reachable
        in_paper = owner in paper_reachable
        if in_model and in_paper:
            return "model-and-paper-reachable"
        if in_model:
            return "model-reachable"
        if in_paper:
            return "paper-reachable"
        if owner in block_headers:
            return "unreachable-block-definition"
        return "unknown-owner"

    @classmethod
    def _parse_layer_names(cls, raw_output: bytes) -> list[str]:
        names: list[str] = []
        for line in cls._decode(raw_output).splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            name = stripped.split("\t")[-1].strip()
            if name.startswith(("+", "-")):
                name = name[1:].strip()
            if name and name not in names:
                names.append(name)
        return names

    @classmethod
    def _summarize_diagnostics(cls, path: Path) -> dict[str, Any]:
        categories: Counter[str] = Counter()
        diagnostic_line_count = 0
        error_line_count = 0
        patterns = (
            ("invalid-page-count", "Invalid num_pages"),
            ("dimension-association", "DIMASSOC"),
            ("dynamic-block", "BLOCKREPRESENTATION"),
            ("hatch-handle-stream", "Skip HATCH common handles"),
            ("unhandled-class", "Unhandled Class object"),
            ("unstable-class", "Unstable Class object"),
        )
        with path.open("rb") as source:
            for raw_line in source:
                line = cls._decode(raw_line).strip()
                if not line or not re.search(r"\b(?:WARNING|ERROR)\b", line, re.IGNORECASE):
                    continue
                diagnostic_line_count += 1
                if re.search(r"\bERROR\b", line, re.IGNORECASE):
                    error_line_count += 1
                category = "other"
                for candidate, pattern in patterns:
                    if pattern in line:
                        category = candidate
                        break
                categories[category] += 1
        return {
            "diagnostic_line_count": diagnostic_line_count,
            "error_line_count": error_line_count,
            "categories": dict(sorted(categories.items())),
        }

    @classmethod
    def _diagnostic_tail(cls, path: Path, byte_limit: int = 4096) -> str:
        if not path.is_file():
            return "<no diagnostics>"
        with path.open("rb") as source:
            source.seek(0, 2)
            source.seek(max(0, source.tell() - byte_limit))
            return cls._decode(source.read()).strip() or "<no diagnostics>"

    @staticmethod
    def _decode(value: bytes) -> str:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return value.decode(encoding)
            except UnicodeDecodeError:
                continue
        return value.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class ValidationCheck:
    check_id: str
    status: str
    blocking: bool
    details: str


@dataclass(frozen=True)
class InspectionWarning:
    code: str
    message: str


@dataclass
class DwgSourceInspection:
    source_asset_id: str
    source_locator: str
    filename: str
    size_bytes: int
    sha256: str
    dwg_signature: str
    dwg_version: str | None
    intake_status: str
    geometry_status: str
    parser: dict[str, str] | None = None
    geometry_metadata: dict[str, Any] = field(default_factory=dict)
    checks: list[ValidationCheck] = field(default_factory=list)
    warnings: list[InspectionWarning] = field(default_factory=list)
    contract_version: str = "1.0"
    media_type: str = "image/vnd.dwg"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checks"] = [asdict(item) for item in self.checks]
        payload["warnings"] = [asdict(item) for item in self.warnings]
        return payload


class DwgIntakeAdapter:
    """Validates a DWG source before any professional geometry parser runs."""

    def __init__(self, parser: CadGeometryParser | None = None) -> None:
        self.parser = parser

    def inspect(
        self,
        source_path: str | Path,
        source_asset_id: str,
        expected_sha256: str | None = None,
        source_locator: str | None = None,
    ) -> DwgSourceInspection:
        path = Path(source_path)
        if not path.is_file():
            raise FileNotFoundError(path)

        size_bytes, sha256, signature = self._fingerprint(path)
        checks: list[ValidationCheck] = []
        warnings: list[InspectionWarning] = []

        extension_valid = path.suffix.lower() == ".dwg"
        checks.append(ValidationCheck(
            "cad.file-extension", "passed" if extension_valid else "failed", True,
            "Source extension is .dwg." if extension_valid else "Source extension must be .dwg.",
        ))

        version = DWG_VERSIONS.get(signature)
        signature_valid = version is not None
        checks.append(ValidationCheck(
            "cad.dwg-signature", "passed" if signature_valid else "failed", True,
            f"Recognized {signature}: {version}." if signature_valid else f"Unsupported DWG signature: {signature or '<empty>'}.",
        ))

        hash_valid = expected_sha256 is None or sha256.casefold() == expected_sha256.casefold()
        checks.append(ValidationCheck(
            "source.sha256", "passed" if hash_valid else "failed", True,
            "Source hash matches the registered asset." if expected_sha256 else "Source hash recorded for this asset.",
        ))

        inspection = DwgSourceInspection(
            source_asset_id=source_asset_id,
            source_locator=source_locator or path.name,
            filename=path.name,
            size_bytes=size_bytes,
            sha256=sha256,
            dwg_signature=signature,
            dwg_version=version,
            intake_status="rejected",
            geometry_status="not-run",
            checks=checks,
            warnings=warnings,
        )

        if not all((extension_valid, signature_valid, hash_valid)):
            if not hash_valid:
                warnings.append(InspectionWarning(
                    "SOURCE_HASH_MISMATCH",
                    "The file does not match the registered source asset; geometry parsing was blocked.",
                ))
            return inspection

        if self.parser is None:
            inspection.intake_status = "geometry-parse-pending"
            warnings.append(InspectionWarning(
                "CAD_GEOMETRY_PARSER_UNAVAILABLE",
                "DWG preflight passed, but no professional geometry parser is configured.",
            ))
            checks.append(ValidationCheck(
                "cad.geometry-parser", "not-run", True,
                "Configure an approved CAD parser before reading layers, entities, dimensions, or bounds.",
            ))
            return inspection

        inspection.parser = {"name": self.parser.name, "version": self.parser.version}
        if not self.parser.supports(signature):
            inspection.intake_status = "geometry-parse-pending"
            inspection.geometry_status = "unsupported"
            warnings.append(InspectionWarning(
                "CAD_VERSION_UNSUPPORTED",
                f"Configured parser does not support {signature}.",
            ))
            checks.append(ValidationCheck(
                "cad.geometry-parser", "not-run", True,
                f"Parser {self.parser.name} {self.parser.version} does not support this DWG version.",
            ))
            return inspection

        try:
            metadata = dict(self.parser.parse(path))
            self._validate_geometry_metadata(metadata)
        except Exception as error:
            inspection.intake_status = "geometry-parse-failed"
            inspection.geometry_status = "failed"
            warnings.append(InspectionWarning("CAD_GEOMETRY_PARSE_FAILED", str(error)))
            checks.append(ValidationCheck(
                "cad.geometry-parser", "failed", True,
                f"Parser {self.parser.name} {self.parser.version} failed.",
            ))
            return inspection

        inspection.intake_status = "geometry-parsed"
        inspection.geometry_status = "succeeded"
        inspection.geometry_metadata = metadata
        parser_quality = str(metadata.get("quality_status", "parsed"))
        has_parser_warnings = parser_quality != "parsed"
        if has_parser_warnings:
            warnings.append(InspectionWarning(
                "CAD_GEOMETRY_PARSE_WARNINGS",
                "Geometry metadata was extracted, but parser compatibility diagnostics require secondary validation.",
            ))
        checks.append(ValidationCheck(
            "cad.geometry-parser", "warning" if has_parser_warnings else "passed", True,
            (
                f"Parser {self.parser.name} {self.parser.version} returned geometry metadata "
                f"with quality status {parser_quality}."
            ),
        ))
        return inspection

    @staticmethod
    def _validate_geometry_metadata(metadata: Mapping[str, Any]) -> None:
        required = {
            "quality_status",
            "requires_secondary_validation",
            "parser_output_validation",
            "drawing_units",
            "object_count",
            "entity_count",
            "non_entity_object_count",
            "entity_type_count",
            "entity_counts",
            "text_entity_count",
            "dimension_entity_count",
            "layer_count",
            "layer_names",
            "layer_statistics",
            "unresolved_layer_reference_count",
            "block_context",
            "global_extents",
            "parser_diagnostics",
        }
        missing = sorted(required.difference(metadata))
        if missing:
            raise RuntimeError(f"Geometry metadata is missing required fields: {', '.join(missing)}")

        quality_status = metadata["quality_status"]
        if quality_status not in {"parsed", "parsed-with-compatibility-warnings"}:
            raise RuntimeError(f"Unsupported geometry quality status: {quality_status}")
        requires_secondary_validation = metadata["requires_secondary_validation"]
        if not isinstance(requires_secondary_validation, bool):
            raise RuntimeError("requires_secondary_validation must be boolean.")
        if requires_secondary_validation != (quality_status != "parsed"):
            raise RuntimeError("Geometry quality status and secondary-validation flag disagree.")

        validation = metadata["parser_output_validation"]
        if not isinstance(validation, Mapping):
            raise RuntimeError("parser_output_validation must be an object.")
        if validation.get("valid_json") is not True or validation.get("required_sections_present") is not True:
            raise RuntimeError("Parser output did not pass JSON completeness validation.")

        count_fields = (
            "object_count",
            "entity_count",
            "non_entity_object_count",
            "entity_type_count",
            "text_entity_count",
            "dimension_entity_count",
            "layer_count",
            "unresolved_layer_reference_count",
        )
        for field_name in count_fields:
            value = metadata[field_name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RuntimeError(f"{field_name} must be a non-negative integer.")

        entity_counts = metadata["entity_counts"]
        if not isinstance(entity_counts, Mapping):
            raise RuntimeError("entity_counts must be an object.")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in entity_counts.values()):
            raise RuntimeError("entity_counts values must be non-negative integers.")
        if sum(entity_counts.values()) != metadata["entity_count"]:
            raise RuntimeError("entity_counts do not add up to entity_count.")
        if len(entity_counts) != metadata["entity_type_count"]:
            raise RuntimeError("entity_type_count does not match entity_counts.")
        if metadata["entity_count"] + metadata["non_entity_object_count"] != metadata["object_count"]:
            raise RuntimeError("Entity and non-entity counts do not add up to object_count.")

        layer_names = metadata["layer_names"]
        if not isinstance(layer_names, list) or not all(isinstance(name, str) and name for name in layer_names):
            raise RuntimeError("layer_names must be a list of non-empty strings.")
        if len(layer_names) != metadata["layer_count"] or len(set(layer_names)) != len(layer_names):
            raise RuntimeError("layer_count does not match the unique layer_names list.")

        layer_statistics = metadata["layer_statistics"]
        if not isinstance(layer_statistics, list) or len(layer_statistics) != metadata["layer_count"]:
            raise RuntimeError("layer_statistics must contain one record per layer.")
        statistic_names = [item.get("name") for item in layer_statistics if isinstance(item, Mapping)]
        if statistic_names != layer_names:
            raise RuntimeError("layer_statistics order does not match layer_names.")
        layer_entity_total = 0
        for item in layer_statistics:
            item_counts = item.get("entity_counts")
            item_total = item.get("entity_count")
            if not isinstance(item_counts, Mapping) or not isinstance(item_total, int):
                raise RuntimeError("Layer entity counts are malformed.")
            if sum(item_counts.values()) != item_total:
                raise RuntimeError(f"Layer {item.get('name')!r} entity counts are inconsistent.")
            context_counts = item.get("block_context_counts")
            if not isinstance(context_counts, Mapping) or sum(context_counts.values()) != item_total:
                raise RuntimeError(f"Layer {item.get('name')!r} block context counts are inconsistent.")
            if not isinstance(item.get("top_owner_blocks"), list):
                raise RuntimeError(f"Layer {item.get('name')!r} owner block summary is missing.")
            layer_entity_total += item_total
        if layer_entity_total + metadata["unresolved_layer_reference_count"] != metadata["entity_count"]:
            raise RuntimeError("Layer statistics do not cover all entities.")

        block_context = metadata["block_context"]
        if not isinstance(block_context, Mapping):
            raise RuntimeError("block_context must be an object.")
        block_entity_counts = block_context.get("entity_context_counts")
        if not isinstance(block_entity_counts, Mapping):
            raise RuntimeError("block_context entity counts must be an object.")
        if sum(block_entity_counts.values()) + metadata["unresolved_layer_reference_count"] != metadata["entity_count"]:
            raise RuntimeError("Block context counts do not cover all entities.")

        diagnostics = metadata["parser_diagnostics"]
        if not isinstance(diagnostics, Mapping) or not isinstance(diagnostics.get("categories"), Mapping):
            raise RuntimeError("parser_diagnostics and its categories must be objects.")
        diagnostic_count = diagnostics.get("diagnostic_line_count")
        error_count = diagnostics.get("error_line_count")
        if not isinstance(diagnostic_count, int) or not isinstance(error_count, int):
            raise RuntimeError("Parser diagnostic counts must be integers.")
        if diagnostic_count < 0 or error_count < 0 or error_count > diagnostic_count:
            raise RuntimeError("Parser diagnostic counts are inconsistent.")
        if sum(diagnostics["categories"].values()) != diagnostic_count:
            raise RuntimeError("Parser diagnostic categories do not add up to the total.")

    @staticmethod
    def _fingerprint(path: Path) -> tuple[int, str, str]:
        digest = hashlib.sha256()
        size_bytes = 0
        signature_bytes = b""
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                if not signature_bytes:
                    signature_bytes = chunk[:6]
                digest.update(chunk)
                size_bytes += len(chunk)
        signature = signature_bytes.decode("ascii", errors="replace")
        return size_bytes, digest.hexdigest().upper(), signature
