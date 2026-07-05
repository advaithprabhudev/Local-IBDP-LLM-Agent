"""File -> card-candidate ingestion pipeline. Parsing is pure; disk/PDF reads are I/O."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

TEXT_EXTENSIONS = {".md", ".txt"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS

_QA_BLOCK_RE = re.compile(
    r"^Q:\s*(?P<question>.+?)\s*\n^A:\s*(?P<answer>.+?)\s*(?=\n\s*\n|\Z)",
    re.MULTILINE | re.DOTALL,
)
_TERM_DEF_RE = re.compile(r"^(?P<term>[^\n:]+?)\s*::\s*(?P<definition>.+)$", re.MULTILINE)


@dataclass(frozen=True)
class CardCandidate:
    front: str
    back: str
    source_file: str
    structured: bool  # True = explicit Q:/A: or "::" syntax; False = needs triage


def normalized_front_hash(front: str) -> str:
    """Hash used for cross-import deduplication of card fronts."""
    normalized = re.sub(r"\s+", " ", front.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_structured_text(text: str, source_file: str) -> list[CardCandidate]:
    """Extract explicit Q:/A: blocks and term :: definition lines from .md/.txt content."""
    candidates: list[CardCandidate] = []
    consumed_spans: list[tuple[int, int]] = []

    for match in _QA_BLOCK_RE.finditer(text):
        candidates.append(
            CardCandidate(
                front=match.group("question").strip(),
                back=match.group("answer").strip(),
                source_file=source_file,
                structured=True,
            )
        )
        consumed_spans.append(match.span())

    for match in _TERM_DEF_RE.finditer(text):
        if any(start <= match.start() < end for start, end in consumed_spans):
            continue
        candidates.append(
            CardCandidate(
                front=match.group("term").strip(),
                back=match.group("definition").strip(),
                source_file=source_file,
                structured=True,
            )
        )

    return candidates


def chunk_unstructured_text(text: str, source_file: str) -> list[CardCandidate]:
    """Split unstructured text into paragraph/heading chunks as unconfirmed triage candidates."""
    chunks = re.split(r"\n\s*\n", text.strip())
    candidates = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        front = lines[0].strip()
        back = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        candidates.append(
            CardCandidate(front=front, back=back, source_file=source_file, structured=False)
        )
    return candidates


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def candidates_for_file(path: Path) -> list[CardCandidate]:
    """Produce card candidates for a single supported file."""
    suffix = path.suffix.lower()
    source_file = str(path)

    if suffix in TEXT_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="replace")
        structured = parse_structured_text(text, source_file)
        if structured:
            return structured
        return chunk_unstructured_text(text, source_file)

    if suffix in PDF_EXTENSIONS:
        text = extract_pdf_text(path)
        return chunk_unstructured_text(text, source_file)

    raise ValueError(f"Unsupported file type: {suffix}")


def iter_supported_files(root: Path) -> list[Path]:
    """Recursively find supported files under a path (file or directory)."""
    if root.is_file():
        return [root] if root.suffix.lower() in SUPPORTED_EXTENSIONS else []
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def dedupe_against_existing(
    candidates: list[CardCandidate], existing_hashes: set[str]
) -> list[CardCandidate]:
    """Drop candidates whose front hash already exists (in this batch or in the DB)."""
    seen = set(existing_hashes)
    kept = []
    for c in candidates:
        h = normalized_front_hash(c.front)
        if h in seen:
            continue
        seen.add(h)
        kept.append(c)
    return kept
