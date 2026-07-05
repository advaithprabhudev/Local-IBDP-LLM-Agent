"""Ingestion: filename metadata parsing, PDF/MD text extraction, chunking.

See ../skills/ib-metadata-conventions/ for the filename convention and enum tables
this module implements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

VALID_SUBJECTS = {"mathaa", "physics"}
VALID_TYPES = {"pp", "ms", "tb", "notes"}
VALID_LEVELS = {"hl", "sl"}
VALID_SESSIONS = {"may", "nov"}
VALID_PAPERS = {"p1", "p2", "p3"}
VALID_TZ = {"", "tz1", "tz2"}
MIN_YEAR = 2014

STANDARD_RE = re.compile(
    r"^(?P<subject>[a-z]+)_(?P<type>pp|ms|notes)_(?P<year>\d{4})_(?P<session>may|nov)_"
    r"(?P<paper>p[123])_(?P<level>hl|sl)(?:_(?P<tz>tz[12]))?$",
    re.IGNORECASE,
)
TEXTBOOK_RE = re.compile(
    r"^(?P<subject>[a-z]+)_tb_(?P<publisher>[a-z0-9]+)_(?P<chapter>[a-z0-9]+)$",
    re.IGNORECASE,
)


@dataclass
class ParsedMeta:
    subject: str
    doc_type: str
    year: int = 0
    session: str = ""
    paper: str = ""
    level: str = ""
    tz: str = ""
    publisher: str = ""
    chapter: str = ""
    parse_quality: str = "ok"


@dataclass
class PageText:
    page: int
    text: str


@dataclass
class Chunk:
    text: str
    metadata: dict[str, str | int] = field(default_factory=dict)


class IngestError(ValueError):
    """Raised for a field value that parsed but fails enum/range validation."""


def _invalid_fields(fields: dict[str, str]) -> list[str]:
    bad = []
    if fields.get("subject", "").lower() not in VALID_SUBJECTS:
        bad.append("subject")
    if fields.get("type", "") not in VALID_TYPES:
        bad.append("type")
    if fields.get("type", "") == "tb":
        return bad
    year = fields.get("year", "")
    if not year.isdigit() or not (MIN_YEAR <= int(year) <= 2100):
        bad.append("year")
    if fields.get("session", "") not in VALID_SESSIONS:
        bad.append("session")
    if fields.get("paper", "") not in VALID_PAPERS:
        bad.append("paper")
    if fields.get("level", "") not in VALID_LEVELS:
        bad.append("level")
    if fields.get("tz", "") not in VALID_TZ:
        bad.append("tz")
    return bad


def parse_filename(name: str) -> tuple[dict[str, str], list[str]]:
    """Best-effort field extraction from an IB filename convention.

    Returns (fields, missing_or_invalid_field_names). An empty second element
    means every field parsed and validated cleanly.
    """
    stem = Path(name).stem.lower()
    m = STANDARD_RE.match(stem)
    if m:
        fields = {k: (v or "") for k, v in m.groupdict().items()}
        return fields, _invalid_fields(fields)
    m = TEXTBOOK_RE.match(stem)
    if m:
        fields = {k: (v or "") for k, v in m.groupdict().items()}
        fields["type"] = "tb"
        return fields, _invalid_fields(fields)
    # Totally unparseable: start from type, since it determines which fields
    # apply (pp/ms/notes need year/session/paper/level; tb needs publisher/chapter).
    return {}, ["subject", "type"]


def prompt_missing_fields(fields: dict[str, str], missing: list[str]) -> dict[str, str]:
    """Interactively prompt (typer) for each missing/invalid field, in order.

    Prompting for "type" first re-derives the remaining required fields, so a
    totally unparseable filename still ends up asking only what's relevant.
    """
    import typer

    fields = dict(fields)
    pending = list(missing)
    while pending:
        f = pending.pop(0)
        fields[f] = typer.prompt(f"  {f}").strip().lower()
        if f == "type":
            if fields["type"] not in VALID_TYPES:
                pending.insert(0, "type")
                continue
            required = (
                ["publisher", "chapter"]
                if fields["type"] == "tb"
                else ["year", "session", "paper", "level"]
            )
            for r in required:
                if r not in fields:
                    pending.append(r)
        elif f in _invalid_fields(fields):
            pending.append(f)
    return fields


def build_parsed_meta(fields: dict[str, str], had_to_prompt: bool) -> ParsedMeta:
    return ParsedMeta(
        subject=fields.get("subject", ""),
        doc_type=fields.get("type", ""),
        year=int(fields["year"]) if fields.get("year", "").isdigit() else 0,
        session=fields.get("session", ""),
        paper=fields.get("paper", ""),
        level=fields.get("level", ""),
        tz=fields.get("tz", ""),
        publisher=fields.get("publisher", ""),
        chapter=fields.get("chapter", ""),
        parse_quality="low" if had_to_prompt else "ok",
    )


def extract_pages(path: Path) -> list[PageText]:
    """Extract per-page text. Scanned/image-only PDF pages are skipped with a warning."""
    if path.suffix.lower() == ".md":
        return [PageText(page=1, text=path.read_text(encoding="utf-8"))]

    pages: list[PageText] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text")
            if not text.strip():
                if page.get_images():
                    print(f"warning: skipping image-only page {i} in {path.name}")
                continue
            pages.append(PageText(page=i, text=text))
    return pages


def _meta_dict(meta: ParsedMeta, filename: str, page: int, question_id: str) -> dict[str, str | int]:
    return {
        "subject": meta.subject,
        "type": meta.doc_type,
        "year": meta.year,
        "session": meta.session,
        "paper": meta.paper,
        "level": meta.level,
        "tz": meta.tz,
        "filename": filename,
        "page": page,
        "question_id": question_id,
        "topic": "",  # keyword classification lands once topic_keywords.toml exists
        "parse_quality": meta.parse_quality,
    }


# Question-boundary hierarchy per skills/markscheme-marking: question -> part -> subpart.
# ponytail: whole-block text extraction only (skill's simplest fallback tier); the
# PyMuPDF table-detection / x-coordinate-splitting tiers for two-column Math AA HL
# layouts are not implemented — add them if plain-text chunks prove unreliable.
Q_RE = re.compile(r"(?m)^\s*(\d{1,2})\s*[.)]?\s")
PART_RE = re.compile(r"\(([a-h])\)")
SUBPART_RE = re.compile(r"\(([ivx]{1,4})\)")
MARK_CODE_RE = re.compile(r"\b(?:M\d|A\d|R\d|AG|ft)\b")
_LEADING_MARKER_RE = re.compile(r"^\s*(?:\d{1,2}\s*[.)]?|\([a-h]\)|\([ivx]{1,4}\))\s*")


def _has_real_content(segment: str) -> bool:
    """False for a segment that is only boundary markers (e.g. "(b) (i)") with
    no actual question/answer text — repeatedly strips leading markers until
    nothing more can be stripped, and checks if anything remains."""
    remainder = segment
    while True:
        stripped = _LEADING_MARKER_RE.sub("", remainder, count=1).strip()
        if stripped == remainder:
            break
        remainder = stripped
    return bool(remainder)


def _question_boundaries(text: str) -> list[tuple[int, int, str]]:
    marks = [(m.start(), 1, m.group(1)) for m in Q_RE.finditer(text)]
    marks += [(m.start(), 2, m.group(1)) for m in PART_RE.finditer(text)]
    marks += [(m.start(), 3, m.group(1)) for m in SUBPART_RE.finditer(text)]
    marks.sort(key=lambda t: t[0])
    return marks


def _make_question_chunk(
    text: str, meta: ParsedMeta, filename: str, page: int, question_id: str
) -> Chunk:
    quality = meta.parse_quality
    if meta.doc_type == "ms" and quality == "ok" and not MARK_CODE_RE.search(text):
        quality = "low"
        print(
            f"warning: no mark codes detected in markscheme chunk "
            f"{question_id or '?'} ({filename} p.{page})"
        )
    metadata = _meta_dict(meta, filename, page, question_id)
    metadata["parse_quality"] = quality
    return Chunk(text, metadata)


def _chunk_by_question(pages: list[PageText], meta: ParsedMeta, filename: str) -> list[Chunk]:
    """Question/part/subpart chunking, used for both markscheme ("ms") and past-paper
    ("pp") docs — quiz pairs a pp question chunk with its ms chunk via question_id."""
    chunks = []
    for page in pages:
        boundaries = _question_boundaries(page.text)
        if not boundaries:
            if page.text.strip():
                chunks.append(
                    _make_question_chunk(page.text.strip(), meta, filename, page.page, "")
                )
            continue
        q = part = subpart = ""
        for i, (pos, level, label) in enumerate(boundaries):
            if level == 1:
                q, part, subpart = label, "", ""
            elif level == 2:
                part, subpart = label, ""
            else:
                subpart = label
            question_id = f"{q}{part}{subpart}"
            end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(page.text)
            segment = page.text[pos:end].strip()
            if segment and _has_real_content(segment):
                chunks.append(
                    _make_question_chunk(segment, meta, filename, page.page, question_id)
                )
    return chunks


def _chunk_sliding_window(
    pages: list[PageText], meta: ParsedMeta, filename: str, size: int = 512, overlap: int = 64
) -> list[Chunk]:
    chunks = []
    step = max(1, size - overlap)
    for page in pages:
        words = page.text.split()
        if not words:
            continue
        i = 0
        while i < len(words):
            window = words[i : i + size]
            chunks.append(
                Chunk(" ".join(window), _meta_dict(meta, filename, page.page, ""))
            )
            if i + size >= len(words):
                break
            i += step
    return chunks


def chunk_document(
    pages: list[PageText], meta: ParsedMeta, filename: str, size: int = 512, overlap: int = 64
) -> list[Chunk]:
    """~512 tokens / 64 overlap (configurable via config.toml's [chunking] table) for
    textbooks/notes. Markscheme and past-paper docs chunk per question instead, so a
    pp question chunk and its ms chunk share a question_id (needed by quiz's reveal flow).

    Chunking runs per-page: a question or window that straddles a page break
    is split at the boundary rather than merged across pages.
    """
    if meta.doc_type in ("ms", "pp"):
        return _chunk_by_question(pages, meta, filename)
    return _chunk_sliding_window(pages, meta, filename, size=size, overlap=overlap)
