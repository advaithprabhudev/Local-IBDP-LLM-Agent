"""Standalone local chat agent over Ollama — fallback for ib-tutor."""

from __future__ import annotations

import io
import sys
from typing import Any, Callable, Protocol, cast

import ollama
import typer
from rich.console import Console

DEFAULT_MODEL = "glm4:9b"
SYSTEM_PROMPT = "You are a helpful local assistant running fully offline via Ollama."

app = typer.Typer(add_completion=False)
console = Console()


class ChatClient(Protocol):
    def chat(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]: ...


class OllamaUnavailable(Exception):
    pass


def send_message(client: ChatClient, model: str, history: list[dict[str, str]]) -> str:
    try:
        response = client.chat(model=model, messages=history)
    except Exception as e:
        raise OllamaUnavailable(
            f"Can't reach Ollama or model '{model}' isn't pulled — "
            f"run `ollama serve` and `ollama pull {model}`."
        ) from e
    return str(response["message"]["content"])


def run_repl(
    model: str,
    client: ChatClient | None = None,
    input_fn: Callable[[], str] | None = None,
) -> None:
    resolved_client: ChatClient = client or cast(ChatClient, ollama.Client())
    resolved_input: Callable[[], str] = input_fn or (lambda: console.input("[bold green]you>[/] "))
    history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    console.print(
        f"[bold cyan]glm-agent[/] — local chat via Ollama ({model}). Type 'exit' to quit."
    )
    while True:
        try:
            user_input = resolved_input()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return

        stripped = user_input.strip()
        if stripped.lower() in {"exit", "quit"}:
            return
        if not stripped:
            continue

        history.append({"role": "user", "content": stripped})
        try:
            reply = send_message(resolved_client, model, history)
        except OllamaUnavailable as e:
            console.print(f"[bold red]error:[/] {e}")
            history.pop()
            continue

        history.append({"role": "assistant", "content": reply})
        console.print(f"[bold magenta]glm>[/] {reply}")


@app.callback()
def _main() -> None:
    """glm-agent: standalone local chat CLI over Ollama."""
    # Windows consoles/pipes often default stdout/stderr to a non-UTF-8 codepage
    # (e.g. cp1252), which can't encode characters (emoji, symbols) local models emit.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")


@app.command()
def chat(
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", envvar="GLM_AGENT_MODEL"),
) -> None:
    """Start an interactive local chat session via Ollama."""
    run_repl(model)


if __name__ == "__main__":
    app()
