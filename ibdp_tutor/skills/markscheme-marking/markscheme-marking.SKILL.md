---
name: markscheme-marking
description: Governs all markscheme parsing, question-boundary chunking, and point-by-point grading logic in ib-tutor. ALWAYS use this skill before writing or modifying the `mark` or `quiz` subcommands, any markscheme ingestion code, question-number regexes, or grading prompts. Also trigger when debugging wrong grades, missed marking points, or markscheme chunks that span multiple questions. Covers IB mark codes (M/A/R/AG/ft), Math AA HL and Physics SL markscheme structure, and the grading output contract.
---

# Markscheme Marking

## IB mark codes (must be parsed and preserved verbatim)

| Code | Meaning | Grading rule |
|---|---|---|
| M | Method mark | Awarded for a valid attempt at the method, even with numerical errors |
| A | Accuracy mark | Requires the correct answer/value; usually dependent on the preceding M |
| R | Reasoning mark | Awarded for correct justification/explanation |
| AG | Answer Given | The answer appears in the question — full working is required; final line alone earns nothing |
| ft | Follow-through | Error carried forward is not re-penalised; grade subsequent steps against the candidate's own earlier value |
| (M1) | Implied mark | Can be awarded if implied by later correct work |
| OE / "or equivalent" | Alternative valid forms accepted | Accept algebraically equivalent expressions |

Physics SL additions: marks per line usually [1] each; "✓" per marking point; accept answers within stated tolerance ranges (e.g. «2.5 ± 0.1» m s⁻¹); unit errors typically lose the final mark only; significant-figure penalty applied at most once per paper.

## Question-boundary chunking

Markscheme chunks must map 1:1 to one part-question. Boundary hierarchy:

1. Question number: `^\s*(\d{1,2})\.?\s` (Math) or `^\s*(\d{1,2})\s*[\.\)]` (Physics)
2. Part: `\(([a-h])\)`
3. Subpart: `\(([ivx]{1,4})\)`

Rules:
- A chunk = the deepest addressable unit (e.g. `3(b)(ii)`), including its total marks tag `[N marks]` or trailing `N` in the marks column.
- Never merge across part boundaaries. Never split a marking-point table mid-row.
- Store `question_id` metadata as canonical string `"{q}{part}{subpart}"`, e.g. `"3bii"`.
- Math AA HL markschemes use two-column layout (working | marks). Extract with PyMuPDF table detection first; fall back to x-coordinate splitting at the marks column; fall back to whole-block text with inline mark codes.
- If parsing confidence is low (no mark codes detected in a chunk claiming to be a markscheme), tag chunk `parse_quality: "low"` and surface a warning at ingest time.

## Grading contract (`mark` subcommand)

Input: candidate answer text + retrieved markscheme chunk for the named question.
Output (rich panel), exactly this structure:

```
Question 3(b)(ii) — [4 marks]
✓ M1  valid substitution into quotient rule        — HIT
✓ A1  correct derivative                            — HIT
✗ R1  justification that f'(x) > 0 on the interval — MISSED: no sign argument given
✗ A1  conclusion (strictly increasing)              — MISSED
Total: 2/4
```

Grading prompt rules (sent to Ollama):
- Enumerate every marking point from the chunk; classify each HIT/MISSED/PARTIAL with a ≤1-line reason.
- Apply ft: if an early A mark is missed, grade later points against the candidate's carried value.
- AG questions: award nothing for restating the given answer without working.
- Never award marks for content not in the markscheme chunk. Never invent marking points.
- If the retrieved chunk's `question_id` does not match the requested question, refuse and report the mismatch — do not grade against the wrong scheme.

## Quiz generation constraints

- Questions must be lifted or minimally adapted from retrieved past-paper chunks — never freely invented.
- Reveal flow: show question → accept attempt → retrieve and display the actual markscheme chunk → run grading contract on the attempt.
- Tag each quiz item with `source: [filename, page]` and command term (e.g. "Show that", "Hence", "Determine").

## Known traps

- "Hence" questions: the markscheme requires use of the previous part's result; an independent method may earn M0 unless scheme says "or otherwise".
- Math AA HL: GDC vs non-GDC — Paper 1 schemes reject calculator-derived values without working; store `paper_number` metadata and include it in the grading prompt.
- Physics SL: ECF across parts is explicit in schemes ("allow ECF from (a)") — only apply ft when stated.
