from __future__ import annotations

from typing import Any

import pytest

from typer.testing import CliRunner

from glm_agent.cli import ChatClient, OllamaUnavailable, app, run_repl, send_message


class FakeChatClient:
    def __init__(self, reply: str = "hi there", raise_error: bool = False) -> None:
        self.reply = reply
        self.raise_error = raise_error
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.calls.append(messages)
        if self.raise_error:
            raise ConnectionError("boom")
        return {"message": {"content": self.reply}}


def test_send_message_returns_reply_content() -> None:
    client: ChatClient = FakeChatClient(reply="42")
    history = [{"role": "user", "content": "what is the answer?"}]

    result = send_message(client, "glm4:9b", history)

    assert result == "42"


def test_send_message_passes_full_history_and_model() -> None:
    fake = FakeChatClient(reply="ok")
    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]

    send_message(fake, "glm4:9b", history)

    assert fake.calls == [history]


def test_send_message_wraps_client_errors() -> None:
    client: ChatClient = FakeChatClient(raise_error=True)
    history = [{"role": "user", "content": "hello"}]

    with pytest.raises(OllamaUnavailable, match="glm4:9b"):
        send_message(client, "glm4:9b", history)


def make_input_fn(*inputs: str):
    it = iter(inputs)

    def _input_fn() -> str:
        return next(it)

    return _input_fn


def test_run_repl_sends_each_turn_and_exits_on_command(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeChatClient(reply="hi there")
    input_fn = make_input_fn("hello", "exit")

    run_repl("glm4:9b", client=fake, input_fn=input_fn)

    out = capsys.readouterr().out
    assert "hi there" in out
    assert len(fake.calls) == 1


def test_run_repl_recovers_after_ollama_error(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeChatClient(raise_error=True)
    input_fn = make_input_fn("hello", "exit")

    run_repl("glm4:9b", client=fake, input_fn=input_fn)

    out = capsys.readouterr().out
    assert "glm4:9b" in out


def test_run_repl_stops_on_eof() -> None:
    fake = FakeChatClient(reply="hi")

    def raise_eof() -> str:
        raise EOFError

    run_repl("glm4:9b", client=fake, input_fn=raise_eof)

    assert fake.calls == []


def test_chat_command_invokes_run_repl(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, str] = {}

    def fake_run_repl(model: str, client: object = None, input_fn: object = None) -> None:
        called["model"] = model

    monkeypatch.setattr("glm_agent.cli.run_repl", fake_run_repl)
    runner = CliRunner()

    result = runner.invoke(app, ["chat", "--model", "glm4:9b"])

    assert result.exit_code == 0
    assert called["model"] == "glm4:9b"
