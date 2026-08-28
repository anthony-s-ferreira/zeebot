"""Resposta local com um pequeno modelo GGUF via llama.cpp."""

from __future__ import annotations

import logging
import re
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
        self.max_tokens = max(8, int(config.get("max_tokens", 48)))
        self.max_words = max(5, int(config.get("max_words", 24)))
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
                        f"Responda diretamente em uma unica frase, com no maximo "
                        f"{self.max_words} palavras, de forma clara e adequada para criancas. "
                        "Nao use introducoes como 'A resposta e', pois a voz acrescentara isso. "
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
        return self._shorten(text)

    def _shorten(self, text: str) -> str:
        """Garante uma frase curta mesmo quando o modelo ignora o prompt."""
        clean = " ".join(str(text or "").split()).strip()
        without_prefix = re.sub(
            r"^(?:a\s+)?resposta\s+(?:é|e)\s*[:,-]?\s*",
            "",
            clean,
            count=1,
            flags=re.IGNORECASE,
        ).strip()
        clean = without_prefix or clean
        first_sentence = re.split(r"(?<=[.!?])\s+", clean, maxsplit=1)[0].strip()
        words = first_sentence.split()
        if len(words) > self.max_words:
            return " ".join(words[: self.max_words]).rstrip(".,;:!?") + "…"
        return first_sentence
