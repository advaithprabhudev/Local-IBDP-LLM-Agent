---
name: ib-metadata-conventions
description: Canonical metadata schema, filename convention, and subject/topic taxonomies for ib-tutor ingestion and retrieval filtering. ALWAYS use this skill before writing or modifying ingestion code, filename parsers, ChromaDB metadata fields, CLI filter flags (--subject, --type, --year, --paper), or the interactive metadata prompt. Also trigger when adding a new subject, debugging filter misses, or normalising document metadata. Covers Mathematics AA HL and Physics SL v1 taxonomies and the extensibility contract for the remaining subjects.
---

# IB Metadata Conventions

## Filename convention (source of truth for auto-metadata)

```
{subject}_{type}_{year}_{session}_{paper}_{level}[_{tz}].{ext}
mathaa_pp_2023_may_p1_hl_tz2.pdf
physics_ms_2022_nov_p2_sl.pdf
mathaa_tb_oxford_ch07.pdf          # textbooks: subject_tb_{publisher}_{chapter}
```

Parse with a single anchored regex; any failed field → interactive prompt (typer) for that field only, never silently default.

## Canonical enums (validate at ingest; reject unknowns with actionable error)

| Field | Values |
|---|---|
| `subject` | `mathaa`, `physics` (v1) — reserved: `econ`, `cs`, `english_ll`, `spanish_ab` |
| `type` | `pp` (past paper), `ms` (markscheme), `tb` (textbook), `notes` |
| `level` | `hl`, `sl` |
| `session` | `may`, `nov` |
| `paper` | `p1`, `p2`, `p3` |
| `tz` | `tz1`, `tz2`, absent |
| `year` | 2014–current; pre-2021 Math AA files: warn (old syllabus, pre-AA split ≤2020) |

## ChromaDB metadata schema (flat, all str/int — Chroma constraint)

```python
{
  "subject": str, "type": str, "year": int, "session": str,
  "paper": str, "level": str, "tz": str,          # "" if absent
  "filename": str, "page": int,
  "question_id": str,                              # "" for textbook chunks; see markscheme-marking
  "topic": str,                                    # from taxonomy below, "" if unclassified
  "parse_quality": str,                            # "ok" | "low"
}
```

Pairing invariant: every `ms` file should have a matching `pp` file on (subject, year, session, paper, level, tz). Report unpaired files at end of ingest — do not block.

## Topic taxonomies (v1)

**Mathematics AA HL** (syllabus topic numbers — use these codes):
- `aa1` Number & Algebra (sequences, binomial, complex numbers, proof, systems)
- `aa2` Functions (graphs, transformations, polynomials, rational, modulus)
- `aa3` Geometry & Trigonometry (vectors, trig identities/equations, 3D)
- `aa4` Statistics & Probability (distributions, binomial/normal, Bayes)
- `aa5` Calculus (limits, differentiation, integration, DEs, Maclaurin)

**Physics SL** (2025 syllabus themes):
- `phyA` Space, time & motion (kinematics, forces, momentum, work/energy)
- `phyB` The particulate nature of matter (thermal, gas laws, current)
- `phyC` Wave behaviour (oscillations, waves, interference, Doppler)
- `phyD` Fields (gravitational, electric, magnetic — SL subset)
- `phyE` Nuclear & quantum (radioactivity, fission/fusion, quantum SL subset)

Topic classification at ingest: keyword-match first (maintain keyword map in `references/topic_keywords.toml` when created); if ambiguous, leave `""` — never guess a topic. `stats` weak-topic ranking groups by these codes.

## CLI filter contract

- `--subject`, `--type`, `--year`, `--paper`, `--level`, `--topic` map 1:1 to metadata fields; combine with AND semantics.
- Accept human aliases and normalise: "math aa", "maths", "AA" → `mathaa`; "markscheme", "MS" → `ms`.
- Filter that matches zero chunks → say so explicitly with the applied filter set; never fall back to unfiltered retrieval silently.

## Extensibility contract

Adding a subject = (1) add enum value, (2) add topic taxonomy block here, (3) add keyword map entries. Zero code changes outside validation tables — if a new subject requires code changes elsewhere, the design is wrong; fix the design.
