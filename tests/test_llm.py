"""Testes do cliente LLM remoto e do contrato de configuração."""

import json

import pytest

from app.llm import LLMUnavailable, RemoteLLM


def test_llm_extrai_resposta_openai_compatible(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "Resposta remota."}}]}
            ).encode()

    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.llm.request.urlopen", fake_urlopen)
    llm = RemoteLLM(
        {
            "enabled": True,
            "url": "https://example.test/v1",
            "model": "modelo-teste",
            "timeout_seconds": 3,
        }
    )

    assert llm.answer("Oi") == "Resposta remota."
    assert captured == {
        "url": "https://example.test/v1/chat/completions",
        "timeout": 3.0,
    }


def test_llm_converte_falha_de_conexao_em_indisponivel(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("sem internet")

    monkeypatch.setattr("app.llm.request.urlopen", fail)
    llm = RemoteLLM({"enabled": True, "url": "https://example.test", "model": "teste"})

    with pytest.raises(LLMUnavailable, match="sem internet"):
        llm.answer("Oi")
    assert llm.last_error == "sem internet"


def test_llm_extrai_output_do_runpod(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"output": {"response": "Resposta RunPod."}}).encode()

    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        return FakeResponse()

    monkeypatch.setattr("app.llm.request.urlopen", fake_urlopen)
    llm = RemoteLLM(
        {
            "enabled": True,
            "provider": "runpod",
            "url": "https://api.runpod.ai/v2/endpoint/runsync",
        }
    )

    assert llm.answer("Oi") == "Resposta RunPod."
    assert captured["url"].endswith("/runsync")
    assert captured["body"]["input"]["prompt"] == "Oi"