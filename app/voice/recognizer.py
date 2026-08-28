"""Camada sobre o Vosk: carga do modelo e captura de comandos.

Estágio 1 (wakeword) usa um reconhecedor com gramática restrita.
Estágio 2 (comando) usa o reconhecedor completo, com detecção de silêncio e
timeout configuráveis para não ficar gravando indefinidamente.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .mic import MicrophoneStream, MicrophoneUnavailable, rms

log = logging.getLogger(__name__)


class VoiceModelError(RuntimeError):
    """Modelo ausente ou impossível de carregar."""


def is_valid_model_dir(path: Path) -> bool:
    """Reconhece os dois formatos de modelo do Vosk.

    * modelos **small** (recomendados no Pi) têm estrutura plana:
      ``final.mdl``, ``HCLr.fst``, ``Gr.fst``, ``mfcc.conf``, ``ivector/``;
    * modelos **grandes** usam subpastas: ``am/final.mdl``, ``graph/``, ``conf/``.
    """
    path = Path(path)
    if not path.is_dir():
        return False
    flat = (path / "final.mdl").exists() and (path / "ivector").is_dir()
    nested = (path / "am" / "final.mdl").exists() or (path / "am").is_dir()
    return flat or nested


def find_model_dir(path: Path) -> Optional[Path]:
    """Aceita também um nível extra de pasta (erro comum ao descompactar)."""
    path = Path(path)
    if is_valid_model_dir(path):
        return path
    if path.is_dir():
        for child in sorted(path.iterdir()):
            if child.is_dir() and is_valid_model_dir(child):
                return child
    return None


class VoskEngine:
    """Encapsula ``vosk.Model`` e a criação de reconhecedores."""

    def __init__(self, model_path: Path, sample_rate: int = 16000) -> None:
        self.model_path = Path(model_path)
        self.sample_rate = int(sample_rate)
        self._model = None
        self._vosk = None

    # ------------------------------------------------------------------ carga
    def load(self) -> None:
        if self._model is not None:
            return
        if not self.model_path.exists():
            raise VoiceModelError(
                f"modelo Vosk não encontrado em {self.model_path}. "
                "Execute scripts/download_vosk_model.sh"
            )

        resolved = find_model_dir(self.model_path)
        if resolved is None:
            # Erro clássico: extrair o zip e apontar para a pasta errada.
            entries = sorted(p.name for p in self.model_path.iterdir())[:10]
            raise VoiceModelError(
                f"{self.model_path} não parece um modelo Vosk válido "
                f"(conteúdo: {entries or 'vazio'})"
            )
        if resolved != self.model_path:
            log.warning("modelo encontrado em subpasta: %s", resolved)
            self.model_path = resolved
        try:
            import vosk
        except ImportError as exc:
            raise VoiceModelError(f"pacote vosk não instalado: {exc}") from exc

        try:
            vosk.SetLogLevel(-1)  # silencia o log verboso do Kaldi
            start = time.time()
            self._model = vosk.Model(str(self.model_path))
            self._vosk = vosk
        except Exception as exc:  # pragma: no cover - depende do modelo
            raise VoiceModelError(f"falha ao carregar o modelo: {exc}") from exc
        log.info("modelo Vosk carregado de %s (%.1fs)", self.model_path, time.time() - start)

    @property
    def loaded(self) -> bool:
        return self._model is not None

    # --------------------------------------------------------- reconhecedores
    def create_recognizer(self, grammar: Optional[str] = None):
        """Cria um ``KaldiRecognizer``; com ``grammar`` fica restrito à lista."""
        if self._model is None:
            raise VoiceModelError("modelo não carregado")
        vosk = self._vosk
        if grammar:
            try:
                recognizer = vosk.KaldiRecognizer(self._model, self.sample_rate, grammar)
                log.info("reconhecedor com gramática restrita ativo: %s", grammar)
            except Exception as exc:
                log.warning(
                    "gramática rejeitada pelo modelo (%s) — usando reconhecedor completo", exc
                )
                recognizer = vosk.KaldiRecognizer(self._model, self.sample_rate)
        else:
            recognizer = vosk.KaldiRecognizer(self._model, self.sample_rate)
        recognizer.SetWords(False)
        return recognizer


def result_text(payload: str) -> str:
    """Extrai ``text``/``partial`` do JSON devolvido pelo Vosk."""
    if not payload:
        return ""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    text = data.get("text") or data.get("partial") or ""
    return str(text).strip()


class CommandRecognizer:
    """Estágio 2: grava até o usuário parar de falar e transcreve."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, sample_rate: int = 16000) -> None:
        self.sample_rate = int(sample_rate)
        self.configure(config or {})

    def configure(self, config: Dict[str, Any]) -> None:
        self.max_record_seconds = float(config.get("max_record_seconds", 10))
        self.min_record_seconds = float(config.get("min_record_seconds", 0.8))
        self.no_speech_timeout = float(config.get("no_speech_timeout_seconds", 5.0))
        self.silence_threshold = float(config.get("silence_rms_threshold", 350))
        self.silence_duration = float(config.get("silence_duration_seconds", 1.2))

    def capture(self, stream: MicrophoneStream, recognizer) -> Tuple[str, Dict[str, Any]]:
        """Captura um comando.  Devolve ``(texto, métricas)``."""
        recognizer.Reset()
        started = time.time()
        speech_started = False
        last_voice = started
        peak = 0.0
        blocks = 0
        finals = []
        reason = "silêncio"

        while True:
            elapsed = time.time() - started
            if elapsed >= self.max_record_seconds:
                reason = "timeout máximo"
                break
            try:
                data = stream.read()
            except MicrophoneUnavailable as exc:
                log.error("captura interrompida: %s", exc)
                reason = "erro de microfone"
                break
            if not data:
                continue

            blocks += 1
            level = rms(data)
            peak = max(peak, level)
            now = time.time()

            if level >= self.silence_threshold:
                if not speech_started:
                    log.debug("início de fala detectado (rms=%.0f)", level)
                speech_started = True
                last_voice = now

            if recognizer.AcceptWaveform(data):
                text = result_text(recognizer.Result())
                if text:
                    finals.append(text)

            if not speech_started and (now - started) >= self.no_speech_timeout:
                reason = "nenhuma fala detectada"
                break
            if (
                speech_started
                and (now - last_voice) >= self.silence_duration
                and (now - started) >= self.min_record_seconds
            ):
                reason = "fim de fala"
                break

        tail = result_text(recognizer.FinalResult())
        if tail:
            finals.append(tail)
        text = " ".join(part for part in finals if part).strip()

        metrics = {
            "duration": round(time.time() - started, 2),
            "blocks": blocks,
            "peak_rms": round(peak, 1),
            "speech_detected": speech_started,
            "stop_reason": reason,
        }
        log.info("transcrição: %r (%s)", text, metrics)
        return text, metrics
