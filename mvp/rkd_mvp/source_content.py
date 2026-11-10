"""AI-DESIGN-01c: deterministic, source-locatable extraction of original file text.

This module never asks a model to guess file contents. It only accepts text that
can be decoded from the stored bytes with an explicit locator. Scanned PDFs,
CID-mapped fonts, CAD binaries and raster images stay ``unknown`` instead of
being turned into invented prose. Extracted text is local-only: callers must
record an explicit decision before any of it is sent to an external model.
"""
from __future__ import annotations

import hashlib
import re
import zlib
from typing import Any

EXTRACTOR_VERSION = "rkd-source-content.v1"
SCHEMA_VERSION = "rkd-ai-source-extraction.v1"

MAX_SEGMENTS = 200
MAX_SEGMENT_CHARS = 2000
MAX_TOTAL_CHARS = 200_000

_PLAIN_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".svg", ".dxf", ".yaml", ".yml"}
_BINARY_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".dwg", ".xls", ".xlsx", ".gif", ".bmp"}

_PDF_OBJECT = re.compile(rb"(\d+)\s+0\s+obj\b(.*?)\bendobj", re.DOTALL)
_PDF_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_PDF_TEXT_BLOCK = re.compile(rb"BT\b(.*?)\bET", re.DOTALL)
_PDF_LITERAL = re.compile(rb"\(((?:\\.|[^\\()])*)\)", re.DOTALL)
_PDF_ESCAPE = re.compile(rb"\\([nrtbf()\\]|[0-7]{1,3})")


def _decode_text(raw: bytes) -> tuple[str | None, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None, "undecodable"


def _visible(value: str) -> bool:
    if not value:
        return False
    printable = sum(1 for char in value if char.isprintable() or char in "\t\r\n")
    return printable / len(value) >= 0.95 and any(char.isalnum() for char in value)


def _clean(value: str) -> str:
    return "".join(char for char in value if char.isprintable() or char in "\t\r\n ").strip()


def _unescape(match: re.Match[bytes]) -> str:
    token = match.group(1)
    simple = {b"n": "\n", b"r": "\r", b"t": "\t", b"b": "\b", b"f": "\f",
              b"(": "(", b")": ")", b"\\": "\\"}
    if token in simple:
        return simple[token]
    try:
        return chr(int(token, 8))
    except ValueError:
        return ""


def _pdf_literal(raw: bytes) -> str:
    return _PDF_ESCAPE.sub(lambda m: _unescape(m), raw).decode("latin-1", errors="replace")


def _segment(segment_id: str, locator: str, text: str, offset: int) -> dict[str, Any]:
    return {"segment_id": segment_id, "locator": locator, "text": text,
            "char_start": offset, "char_end": offset + len(text)}


def _plain_text_segments(raw: bytes) -> tuple[str, list[dict[str, Any]], list[str]]:
    text, encoding = _decode_text(raw)
    if text is None:
        return "", [], ["文本编码无法识别，未生成内容"]
    warnings: list[str] = []
    if encoding != "utf-8-sig":
        warnings.append(f"按 {encoding} 解码，非 UTF-8 来源需人工复核")
    lines = text.splitlines() or [text]
    segments: list[dict[str, Any]] = []
    offset = 0
    buffer: list[str] = []
    start_line = 1
    for index, line in enumerate(lines, start=1):
        candidate = _clean(line)
        if not buffer:
            start_line = index
        buffer.append(candidate)
        joined = "\n".join(buffer)
        if len(joined) >= 600 or index - start_line + 1 >= 20 or index == len(lines):
            joined = joined[:MAX_SEGMENT_CHARS]
            if joined.strip():
                segments.append(_segment(f"seg-{len(segments) + 1:03d}",
                                         f"line:{start_line}-{index}", joined, offset))
                offset += len(joined) + 1
            buffer = []
        if len(segments) >= MAX_SEGMENTS or offset >= MAX_TOTAL_CHARS:
            warnings.append(f"内容超过本地抽取上限，仅保留前 {len(segments)} 段")
            break
    return text, segments, warnings


def _pdf_text_segments(raw: bytes) -> tuple[str, list[dict[str, Any]], list[str], str]:
    if b"/Encrypt" in raw[:4096] or b"/Encrypt" in raw[-4096:]:
        return "", [], [], "encrypted_pdf"
    warnings: list[str] = []
    objects = _PDF_OBJECT.findall(raw)
    if not objects:
        return "", [], [], "pdf_object_scan_failed"
    content_objects: list[tuple[str, bytes, str]] = []
    for number, body in objects:
        object_id = number.decode("ascii", errors="replace")
        stream = _PDF_STREAM.search(body)
        if not stream:
            continue
        payload = stream.group(1)
        if b"FlateDecode" in body[:stream.start()]:
            try:
                payload = zlib.decompress(payload)
            except zlib.error:
                warnings.append(f"对象 {object_id} 的压缩流无法解压，跳过")
                continue
        if b"BT" not in payload:
            continue
        locator_kind = "pdf-page" if b"/Type /Page" in body[:stream.start()] or b"/Type/Page" in body[:stream.start()] else "pdf-object"
        content_objects.append((object_id, payload, locator_kind))
    if not content_objects:
        warnings.append("未发现可解码的文本内容流；可能是扫描件、矢量轮廓或使用 CID 字体")
        return "", [], warnings, "no_extractable_text_layer"
    segments: list[dict[str, Any]] = []
    offset = 0
    for object_id, payload, locator_kind in content_objects:
        for block_index, block in enumerate(_PDF_TEXT_BLOCK.findall(payload), start=1):
            pieces = [_pdf_literal(literal) for literal in _PDF_LITERAL.findall(block)]
            joined = _clean(" ".join(piece for piece in pieces if piece.strip()))
            if not joined or not _visible(joined):
                warnings.append(f"对象 {object_id} 第 {block_index} 个文本块无法可靠解码，未采用")
                continue
            joined = joined[:MAX_SEGMENT_CHARS]
            segments.append(_segment(f"seg-{len(segments) + 1:03d}",
                                     f"{locator_kind}:{object_id}#text-block:{block_index}", joined, offset))
            offset += len(joined) + 1
            if len(segments) >= MAX_SEGMENTS or offset >= MAX_TOTAL_CHARS:
                warnings.append(f"内容超过本地抽取上限，仅保留前 {len(segments)} 段")
                break
        if len(segments) >= MAX_SEGMENTS or offset >= MAX_TOTAL_CHARS:
            break
    if not segments:
        warnings.append("所有文本块都无法按可见字符可靠解码，不生成猜测内容")
        return "", [], warnings, "no_extractable_text_layer"
    warnings.append("PDF 文本按内容流/文本块定位，页码映射未核验；中文 CID 字体未做映射")
    text = "\n".join(segment["text"] for segment in segments)
    return text, segments, warnings, "extracted"


def build_extraction(*, extraction_id: str, file_id: str, filename: str, file_sha256: str,
                     size_bytes: int, raw: bytes, created_at: str) -> dict[str, Any]:
    """Return a versioned extraction record. Never returns invented content."""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    segments: list[dict[str, Any]] = []
    warnings: list[str] = []
    status = "unsupported_format"
    reason = ""
    extractor_kind = "unsupported"
    text = ""
    if suffix in _PLAIN_SUFFIXES:
        extractor_kind = "plain_text"
        text, segments, warnings = _plain_text_segments(raw)
        if segments:
            status = "extracted"
        else:
            status = "no_extractable_text_layer"
            reason = "文件没有可读取的可见文本"
    elif suffix == ".pdf":
        extractor_kind = "pdf_text_layer"
        text, segments, warnings, outcome = _pdf_text_segments(raw)
        if outcome == "encrypted_pdf":
            status = "unsupported_format"
            reason = "PDF 已加密，本地抽取器不处理加密文件"
        elif outcome == "pdf_object_scan_failed":
            status = "unsupported_format"
            reason = "PDF 对象结构无法可靠扫描，未生成内容"
        elif outcome == "no_extractable_text_layer":
            status = "no_extractable_text_layer"
            reason = "未发现可可靠解码的文本层；扫描件、矢量轮廓和 CID 字体不推断内容"
        else:
            status = "extracted"
    else:
        status = "unsupported_format"
        reason = "该格式本切片不解析（CAD/电子表格/图片等需专门执行器），不生成猜测内容"
    if status != "extracted":
        text = ""
        segments = []
    else:
        # The digest must cover exactly the locatable segments we persist, not
        # the whole decoded file (which may contain lines we intentionally skip).
        text = "\n".join(segment["text"] for segment in segments)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
    return {
        "schema_version": SCHEMA_VERSION,
        "extraction_id": extraction_id,
        "file_id": file_id,
        "filename": filename,
        "file_sha256": file_sha256,
        "size_bytes": size_bytes,
        "extractor_kind": extractor_kind,
        "extractor_version": EXTRACTOR_VERSION,
        "status": status,
        "status_reason": reason or None,
        "segment_count": len(segments),
        "segments": segments,
        "text_sha256": digest,
        "warnings": warnings,
        "truncated": any("上限" in item for item in warnings),
        "content_policy": "local_only_not_sent_to_model_without_explicit_approval",
        "created_at": created_at,
    }


def extraction_summary(record: dict[str, Any]) -> dict[str, Any]:
    """Small, safe projection used inside an AI requirement context manifest."""
    first = record["segments"][0]["locator"] if record.get("segments") else None
    return {"extraction_id": record["extraction_id"], "status": record["status"],
            "segment_count": int(record["segment_count"]), "file_sha256": record["file_sha256"],
            "extractor_version": record["extractor_version"],
            "content_locator": first, "status_reason": record.get("status_reason")}
