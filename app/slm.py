"""Resposta local com um pequeno modelo GGUF via llama.cpp."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class SLMUnavailable(RuntimeError):
    """O modelo ou o runtime local não está disponível."""


class LocalSLM:
    """Carrega o SLM sob demanda para não consumir RAM no boot."""

    def __init__(self, config: Optional[dict] = None) -> None:
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.model_path = Path(config.get("model_path", "models/slm/model.gguf"))
        self.n_ctx = int(config.get("context_size", 512))
        self.max_tokens = int(config.get("max_tokens", 96))
        self.temperature = float(config.get("temperature", 0.2))
        self.threads = int(config.get("threads", 3))
        self._model = None
        self._load_lock = threading.Lock()
        self.last_error: Optional[str] = None

    def _load(self):
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            if not self.enabled:
                raise SLMUnavailable("SLM desativado na configuração")
            if not self.model_path.is_absolute():
                from .config import BASE_DIR

                self.model_path = BASE_DIR / self.model_path
            if not self.model_path.is_file():
                raise SLMUnavailable(f"modelo SLM não encontrado: {self.model_path}")
            try:
                from llama_cpp import Llama
            except ImportError as exc:
                raise SLMUnavailable("llama-cpp-python não instalado") from exc
            log.info("carregando SLM local: %s", self.model_path)
            self._model = Llama(
                model_path=str(self.model_path),
                n_ctx=self.n_ctx,
                n_threads=self.threads,
                verbose=False,
            )
            self.last_error = None
        return self._model

    def warm_up(self) -> bool:
        """Carrega os pesos sem gerar resposta, reduzindo a primeira latência."""
        try:
            self._load()
            return True
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("não foi possível aquecer o SLM: %s", exc)
            return False

    def answer(self, question: str) -> str:
        model = self._load()
        result = model.create_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Voce e Zee, uma assistente educacional em portugues do Brasil. "
                        "Responda de forma curta, clara e adequada para criancas. "
                        "Nao invente recursos do catalogo nem diga que pode abrir sites."
                    ),
                },
                {"role": "user", "content": question.strip()},
            ],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stop=["<|im_end|>", "<|eot_id|>"],
        )
        text = str(result["choices"][0]["message"].get("content", "")).strip()
        if not text:
            raise SLMUnavailable("SLM retornou uma resposta vazia")
        return text
