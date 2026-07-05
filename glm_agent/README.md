# glm-agent

Local, offline chat CLI over Ollama. Fallback for when `ib-tutor`'s model
isn't usable.

## Setup

```bash
ollama pull glm4:9b
uv sync
uv run glm-agent chat
```

Use a different model:

```bash
uv run glm-agent chat --model glm-4.7-flash:latest
# or
GLM_AGENT_MODEL=glm-4.7-flash:latest uv run glm-agent chat
```

Type `exit` or `quit` (or Ctrl+C) to leave the session.
