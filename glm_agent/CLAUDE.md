# CLAUDE.md — glm-agent

Standalone, general-purpose local chat CLI. Fallback for when ib-tutor's RAG
pipeline or its configured model isn't usable.

## Scope

- Pure chat over Ollama. No retrieval, no citations, no IB grounding rules —
  that's ib-tutor's job.
- Single command: `glm-agent chat`. No subcommands unless a real need shows up.
- Default model: `glm4:9b` (5.5GB). Override with `--model`/`-m` or
  `GLM_AGENT_MODEL`. Heavier option if quality is lacking:
  `glm-4.7-flash:latest` (19GB, strongest local-capable GLM tag on Ollama as
  of 2026-07 — `glm-5.1` is cloud-only/756B and cannot run locally).

## Stack

- Python 3.11+, typer + rich + ollama. Non-streaming (single request/response
  per turn) — keep it simple.
- Graceful failure: if Ollama isn't reachable or the model isn't pulled,
  print one actionable line and let the user retry the turn — never crash
  the REPL.

## Out of scope

Multi-agent orchestration, tool calling, persistent chat history across
sessions, RAG. This is a plain chat fallback, not ib-tutor's replacement.
