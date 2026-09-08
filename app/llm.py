"""Cliente para APIs de chat compatíveis com o formato OpenAI."""

from __future__ import annotations

import json
import logging
import os
from typing import Optional
from urllib import request

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """A API remota não pôde produzir uma resposta válida."""


class RemoteLLM:
    """Consulta llama-server local ou RunPod sem depender de SDK externo."""

    def __init__(self, config: Optional[dict] = None) -> None:
        config = config or {}
        self.enabled = bool(config.get("enabled", False))
        self.provider = str(config.get("provider", "openai_compatible")).strip().lower()
        self.url = str(config.get("url", "")).strip().rstrip("/")
        self.model = str(config.get("model", "")).strip()
        self.api_key_env = str(config.get("api_key_env", "LLM_API_KEY")).strip()
        self.timeout = max(1.0, float(config.get("timeout_seconds", 10)))
        self.max_tokens = max(8, int(config.get("max_tokens", 48)))
        self.temperature = float(config.get("temperature", 0.2))
        self.last_error: Optional[str] = None

    def answer(self, question: str) -> str:
        if not self.enabled:
            raise LLMUnavailable("LLM remoto desativado na configuração")
        if not self.url:
            raise LLMUnavailable("URL da API LLM não configurada")
        if self.provider not in {"openai_compatible", "runpod"}:
            raise LLMUnavailable(f"provedor LLM não suportado: {self.provider}")
        if self.provider == "openai_compatible" and not self.model:
            raise LLMUnavailable("modelo da API LLM não configurado")

        system_prompt = (
            "Voce e Zee, uma assistente educacional em portugues do Brasil. "
            "Responda diretamente em uma unica frase, de forma clara e adequada "
            "para criancas. Nao repita a pergunta."
        )
        if self.provider == "runpod":
            endpoint = self.url
            body = {
                "input": {
                    "prompt": question.strip(),
                    "system_prompt": system_prompt,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                }
            }
        else:
            endpoint = f"{self.url}/chat/completions"
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question.strip()},
                ],
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
        payload = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        api_key = os.getenv(self.api_key_env) if self.api_key_env else None
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            with request.urlopen(
                request.Request(endpoint, data=payload, headers=headers),
                timeout=self.timeout,
            ) as response:
                result = json.load(response)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.last_error = str(exc)
            raise LLMUnavailable(f"falha na API LLM: {exc}") from exc

        text = self._extract_text(result)
        if text is None:
            self.last_error = "resposta inválida da API"
            raise LLMUnavailable(self.last_error)
        if not text.strip():
            self.last_error = "API LLM retornou uma resposta vazia"
            raise LLMUnavailable(self.last_error)
        self.last_error = None
        return text.strip()

    def _extract_text(self, result) -> Optional[str]:
        """Aceita respostas OpenAI e as formas comuns de output do RunPod."""
        if not isinstance(result, dict):
            return None
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            if isinstance(message, dict) and message.get("content") is not None:
                return str(message["content"])
        output = result.get("output")
        if isinstance(output, str):
            return output
        if isinstance(output, dict):
            for key in ("response", "text", "generated_text", "content"):
                if output.get(key) is not None:
                    return str(output[key])
            return self._extract_text(output)
        if isinstance(output, list) and output:
            return self._extract_text(output[0])
        return None
