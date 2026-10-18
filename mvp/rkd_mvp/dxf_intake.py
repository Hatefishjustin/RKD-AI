from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


DXF_VERSIONS = {
    "AC1009": "AutoCAD R12",
    "AC1012": "AutoCAD 13",
    "AC1014": "AutoCAD 14",
    "AC1015": "AutoCAD 2000/2000i/2002",
    "AC1018": "AutoCAD 2004/2005/2006",
    "AC1021": "AutoCAD 2007/2008/2009",
    "AC1024": "AutoCAD 2010/2011/2012",
    "AC1027": "AutoCAD 2013-2017",
    "AC1032": "AutoCAD 2018-2026",
}

DXF_UNITS = {
    0: "unitless",
    1: "inches",
    2: "feet",
    3: "miles",
    4: "millimeters",
    5: "centimeters",
    6: "meters",
    7: "kilometers",
    10: "yards",
}


class DxfParseError(RuntimeError):
    """Raised when a DXF cannot be safely interpreted as a second-channel input."""


def _decode_dxf(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "gb18030", "cp1252"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replacement"


def _as_float(value: str) -> float | None:
    if value is None:
        return None
    try:
        number = float(value.strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _as_int(value: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _dxf_text(value: str) -> str:
    r"""Decode AutoCAD's ASCII \U+XXXX escape form without changing other text."""
    return re.sub(
        r"\\U\+([0-9A-Fa-f]{4})",
        lambda match: chr(int(match.group(1), 16)),
        value,
    )


def _pairs(lines: list[str]) -> Iterable[tuple[int, str]]:
    if len(lines) % 2:
        raise DxfParseError("DXF group-code stream has an unmatched final line.")
    for index in range(0, len(lines), 2):
        raw_code = lines[index].strip()
        try:
            code = int(raw_code)
        except ValueError as error:
            raise DxfParseError(f"Invalid DXF group code at line {index + 1}: {raw_code!r}") from error
        if not -5 <= code <= 1071:
            raise DxfParseError(f"DXF group code out of range at line {index + 1}: {code}")
        yield code, lines[index + 1]


def _sections(pairs: list[tuple[int, str]]) -> dict[str, list[tuple[int, str]]]:
    sections: dict[str, list[tuple[int, str]]] = defaultdict(list)
    current: str | None = None
    for code, value in pairs:
        text = value.strip()
        if code == 0 and text == "SECTION":
            current = None
            continue
        if current is None and code == 2:
            current = text.upper()
            continue
        if code == 0 and text == "ENDSEC":
            current = None
            continue
        if current is not None:
            sections[current].append((code, value))
    if "ENTITIES" not in sections:
        raise DxfParseError("DXF has no ENTITIES section.")
    return dict(sections)


def _records(section: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    records: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] | None = None
    for code, value in section:
        if code == 0:
            if current:
                records.append(current)
            current = [(code, value)]
        elif current is not None:
            current.append((code, value))
    if current:
        records.append(current)
    return records


def _field(record: list[tuple[int, str]], code: int, default: str | None = None) -> str | None:
    for current_code, value in record:
        if current_code == code:
            return value
    return default


def _record_bounds(record: list[tuple[int, str]]) -> tuple[list[float], list[float]] | None:
    xs: list[float] = []
    ys: list[float] = []
    for code, value in record:
        if code in (10, 11, 12, 13, 14, 15, 16, 17, 18, 19):
            parsed = _as_float(value)
            if parsed is not None:
                xs.append(parsed)
        elif code in (20, 21, 22, 23, 24, 25, 26, 27, 28, 29):
            parsed = _as_float(value)
            if parsed is not None:
                ys.append(parsed)
    if not xs or not ys:
        return None
    return [min(xs), min(ys)], [max(xs), max(ys)]


class DxfSecondaryValidator:
    """Reads a text DXF conservatively for comparison with a primary CAD parser.

    This is intentionally a summary reader, not a drawing engine. It does not expand
    blocks, infer walls, close regions, calculate quantities, or approve construction.
    """

    name = "RKD ASCII DXF summary reader"
    version = "1.0"

    def parse(self, source_path: str | Path) -> dict[str, Any]:
        path = Path(source_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.suffix.lower() != ".dxf":
            raise DxfParseError("Secondary CAD input must use the .dxf extension.")
        raw = path.read_bytes()
        text, encoding = _decode_dxf(raw)
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        pairs = list(_pairs(lines))
        sections = _sections(pairs)
        header = self._header(sections.get("HEADER", []))
        layer_names = self._layers(sections.get("TABLES", []))
        entities = self._entity_summary(sections.get("ENTITIES", []))
        blocks = self._block_summary(sections.get("BLOCKS", []))
        version = header.get("$ACADVER")
        return {
            "contract_version": "1.0",
            "source_filename": path.name,
            "source_size_bytes": len(raw),
            "source_sha256": hashlib.sha256(raw).hexdigest().upper(),
            "parser": {"name": self.name, "version": self.version},
            "encoding": encoding,
            "dxf_version": version,
            "dxf_version_name": DXF_VERSIONS.get(str(version), "unknown"),
            "drawing_units": {
                "code": header.get("$INSUNITS"),
                "name": DXF_UNITS.get(header.get("$INSUNITS"), "unknown"),
            },
            "global_extents": {
                "minimum": header.get("$EXTMIN"),
                "maximum": header.get("$EXTMAX"),
                "usage": "diagnostic-only; copied from DXF HEADER and not a site measurement",
            },
            "layer_names": layer_names,
            "layer_count": len(layer_names),
            "entities": entities,
            "blocks": blocks,
            "status": "secondary-summary-read",
            "warnings": [
                {
                    "code": "DXF_SUMMARY_ONLY",
                    "message": "This reader does not expand blocks or create professional CAD objects.",
                },
                {
                    "code": "SECOND_ENGINE_REVIEW_REQUIRED",
                    "message": "A summary match is evidence for review, not approval for quantities or construction.",
                },
            ],
        }

    @staticmethod
    def _header(section: list[tuple[int, str]]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        current_variable: str | None = None
        coordinates: dict[str, list[float]] = defaultdict(list)
        for code, value in section:
            if code == 9:
                current_variable = value.strip()
                continue
            if current_variable is None:
                continue
            if code == 70:
                parsed = _as_int(value)
                if parsed is not None:
                    values[current_variable] = parsed
            elif code in (10, 20, 30):
                parsed = _as_float(value)
                if parsed is not None:
                    coordinates[current_variable].append(parsed)
            elif code in (1, 2, 3):
                values[current_variable] = _dxf_text(value.strip())
        for name, numbers in coordinates.items():
            if name in {"$EXTMIN", "$EXTMAX"} and len(numbers) >= 2:
                values[name] = numbers[:3]
        return values

    @staticmethod
    def _layers(section: list[tuple[int, str]]) -> list[str]:
        names: list[str] = []
        in_layer_table = False
        for record in _records(section):
            if _field(record, 0, "").strip().upper() == "TABLE":
                in_layer_table = _field(record, 2, "").strip().upper() == "LAYER"
                continue
            if _field(record, 0, "").strip().upper() == "ENDTAB":
                in_layer_table = False
                continue
            if in_layer_table and _field(record, 0, "").strip().upper() == "LAYER":
                name = _dxf_text(_field(record, 2, "").strip())
                if name and name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _entity_summary(section: list[tuple[int, str]]) -> dict[str, Any]:
        records = _records(section)
        type_counts: Counter[str] = Counter()
        layer_counts: Counter[str] = Counter()
        model_counts: Counter[str] = Counter()
        paper_counts: Counter[str] = Counter()
        handles: set[str] = set()
        minimum: list[float] | None = None
        maximum: list[float] | None = None
        for record in records:
            entity_type = _field(record, 0, "").strip().upper()
            if not entity_type or entity_type in {"ENDSEC", "SECTION"}:
                continue
            type_counts[entity_type] += 1
            layer_counts[_dxf_text(_field(record, 8, "0").strip()) or "0"] += 1
            space = _as_int(_field(record, 67, "0") or "0")
            layout = _dxf_text(_field(record, 410, "Model").strip())
            target = paper_counts if space == 1 or layout.casefold() != "model" else model_counts
            target[entity_type] += 1
            handle = _field(record, 5)
            if handle:
                handles.add(handle.strip().upper())
            bounds = _record_bounds(record)
            if bounds is not None:
                lower, upper = bounds
                minimum = lower if minimum is None else [min(minimum[0], lower[0]), min(minimum[1], lower[1])]
                maximum = upper if maximum is None else [max(maximum[0], upper[0]), max(maximum[1], upper[1])]
        dimensions = sum(count for name, count in type_counts.items() if name.startswith("DIMENSION"))
        text = sum(type_counts.get(name, 0) for name in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"))
        return {
            "entity_count": sum(type_counts.values()),
            "entity_type_count": len(type_counts),
            "entity_counts": dict(sorted(type_counts.items())),
            "layer_entity_counts": dict(sorted(layer_counts.items())),
            "model_space_entity_count": sum(model_counts.values()),
            "model_space_entity_counts": dict(sorted(model_counts.items())),
            "paper_space_entity_count": sum(paper_counts.values()),
            "paper_space_entity_counts": dict(sorted(paper_counts.items())),
            "text_entity_count": text,
            "dimension_entity_count": dimensions,
            "unique_handle_count": len(handles),
            "geometry_extents": {"minimum": minimum, "maximum": maximum},
        }

    @staticmethod
    def _block_summary(section: list[tuple[int, str]]) -> dict[str, Any]:
        records = _records(section)
        names: list[str] = []
        entity_counts: dict[str, int] = {}
        current_name: str | None = None
        current_count = 0
        for record in records:
            kind = _field(record, 0, "").strip().upper()
            if kind == "BLOCK":
                if current_name is not None:
                    entity_counts[current_name] = current_count
                current_name = _dxf_text(_field(record, 2, "").strip()) or "<unnamed>"
                names.append(current_name)
                current_count = 0
            elif kind == "ENDBLK" and current_name is not None:
                entity_counts[current_name] = current_count
                current_name = None
            elif current_name is not None and kind:
                current_count += 1
        if current_name is not None and current_name not in entity_counts:
            entity_counts[current_name] = current_count
        return {
            "block_definition_count": len(names),
            "block_names": names,
            "non_empty_block_definition_count": sum(value > 0 for value in entity_counts.values()),
            "block_entity_counts": entity_counts,
        }


def compare_dxf_to_dwg(
    dxf_summary: Mapping[str, Any],
    dwg_inspection: Mapping[str, Any],
    *,
    layer_name_limit: int = 200,
) -> dict[str, Any]:
    """Compare only stable summary facts; never promotes DXF data to approved geometry."""
    metadata = dwg_inspection.get("geometry_metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("DWG inspection has no geometry_metadata to compare.")
    dxf_entities = dxf_summary.get("entities")
    if not isinstance(dxf_entities, Mapping):
        raise ValueError("DXF summary has no entities section.")
    checks: list[dict[str, Any]] = []

    def add(check_id: str, left: Any, right: Any, *, comparable: bool = True, equal: Any = None) -> None:
        if not comparable:
            status = "not-comparable"
        else:
            status = "match" if (equal(left, right) if callable(equal) else left == right) else "difference"
        checks.append({"check_id": check_id, "status": status, "dxf_value": left, "dwg_value": right})

    def close_extents(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        for key in ("minimum", "maximum"):
            left_values = left.get(key)
            right_values = right.get(key)
            if not isinstance(left_values, list) or not isinstance(right_values, list) or len(left_values) != len(right_values):
                return False
            if any(abs(float(a) - float(b)) > 0.01 for a, b in zip(left_values, right_values)):
                return False
        return True

    add("drawing-units", dxf_summary.get("drawing_units", {}).get("name"), metadata.get("drawing_units", {}).get("name"))
    add("layer-count", dxf_summary.get("layer_count"), metadata.get("layer_count"))
    dxf_layers = set(dxf_summary.get("layer_names", [])[:layer_name_limit])
    dwg_layers = set(metadata.get("layer_names", [])[:layer_name_limit])
    add("layer-name-set", sorted(dxf_layers), sorted(dwg_layers), comparable=True)
    add("entity-count", dxf_entities.get("entity_count"), metadata.get("entity_count"), comparable=True)
    add("entity-type-count", dxf_entities.get("entity_type_count"), metadata.get("entity_type_count"), comparable=True)
    add("text-entity-count", dxf_entities.get("text_entity_count"), metadata.get("text_entity_count"), comparable=True)
    add("dimension-entity-count", dxf_entities.get("dimension_entity_count"), metadata.get("dimension_entity_count"), comparable=True)
    dwg_extents = metadata.get("global_extents", {})
    dxf_extents = dxf_summary.get("global_extents", {})
    dxf_extent_values = {
        "minimum": dxf_extents.get("minimum"),
        "maximum": dxf_extents.get("maximum"),
    }
    dwg_extent_values = {
        "minimum": dwg_extents.get("minimum"),
        "maximum": dwg_extents.get("maximum"),
    }
    add(
        "header-extents",
        dxf_extent_values,
        dwg_extent_values,
        comparable=bool(dxf_extent_values["minimum"] and dxf_extent_values["maximum"]),
        equal=close_extents,
    )
    differences = [item["check_id"] for item in checks if item["status"] == "difference"]
    matches = [item["check_id"] for item in checks if item["status"] == "match"]
    return {
        "comparison_status": "compared-with-differences" if differences else "summary-matched",
        "checks": checks,
        "matching_check_ids": matches,
        "difference_check_ids": differences,
        "promotion_status": "not-approved",
        "warnings": [
            {
                "code": "SUMMARY_COMPARISON_NOT_GEOMETRY_APPROVAL",
                "message": "Counts and names can match while block transforms or topology still differ; professional review remains required.",
            },
        ],
    }
