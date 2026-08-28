"""Camada sobre o Vosk: carga do modelo e captura de comandos.

Estágio 1 (wakeword) usa um reconhecedor com gramática restrita.
Estágio 2 (comando) usa o reconhecedor completo, com detecção de silêncio e
timeout configuráveis para não ficar gravando indefinidamente.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from .mic import MicrophoneStream, MicrophoneUnavailable, rms

log = logging.getLogger(__name__)


class VoiceModelError(RuntimeError):
    """Modelo ausente ou impossível de carregar."""


class OfflineTranscriber(Protocol):
    """Contrato mínimo para um transcritor que recebe PCM mono de 16 bits."""

    def transcribe(self, pcm: bytes, sample_rate: int) -> str: ...


class WhisperCppTranscriber:
    """Transcrição offline pelo executável leve do whisper.cpp."""

    def __init__(
        self,
        binary: str,
        model_path: Path,
        language: str = "pt",
        threads: int = 3,
        timeout_seconds: float = 30,
        enabled: bool = True,
        persistent: bool = True,
        server_binary: Optional[str] = None,
        server_host: str = "127.0.0.1",
        server_port: int = 8178,
        server_startup_timeout: float = 30,
    ) -> None:
        self.enabled = bool(enabled)
        self.binary = self._find_binary(binary)
        self.model_path = Path(model_path)
        self.language = str(language or "pt")
        self.threads = max(1, int(threads))
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.persistent = bool(persistent)
        default_server = str(Path(binary).with_name("whisper-server"))
        self.server_binary = self._find_binary(server_binary or default_server)
        self.server_host = str(server_host or "127.0.0.1")
        self.server_port = int(server_port)
        self.server_startup_timeout = max(1.0, float(server_startup_timeout))
        self._server_process: Optional[subprocess.Popen] = None
        self._server_lock = threading.Lock()
        self._server_ready = threading.Event()

    @staticmethod
    def _find_binary(binary: str) -> Optional[Path]:
        found = shutil.which(str(binary))
        if found:
            return Path(found)
        candidate = Path(str(binary)).expanduser()
        return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.binary and self.model_path.is_file())

    @property
    def server_ready(self) -> bool:
        process = self._server_process
        return bool(
            self._server_ready.is_set()
            and process is not None
            and process.poll() is None
        )

    def start_server(self, blocking: bool = False) -> bool:
        """Inicia um whisper-server local que mantém o modelo na memória."""
        if not (self.enabled and self.persistent and self.server_binary and self.model_path.is_file()):
            return False
        created = False
        with self._server_lock:
            if self.server_ready:
                return True
            if self._server_process is None or self._server_process.poll() is not None:
                self._server_ready.clear()
                command = [
                    str(self.server_binary),
                    "-m", str(self.model_path),
                    "-l", self.language,
                    "-t", str(self.threads),
                    "-nt", "-ng", "--convert",
                    "--host", self.server_host,
                    "--port", str(self.server_port),
                ]
                try:
                    self._server_process = subprocess.Popen(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    created = True
                    log.info("whisper-server iniciando em %s", self.server_url)
                except OSError as exc:
                    log.warning("não foi possível iniciar whisper-server: %s", exc)
                    self._server_process = None
                    return False
        if blocking:
            return self._wait_for_server()
        if created:
            threading.Thread(
                target=self._wait_for_server,
                daemon=True,
                name="zee-whisper-server-start",
            ).start()
        return self.server_ready

    @property
    def server_url(self) -> str:
        return f"http://{self.server_host}:{self.server_port}"

    def _wait_for_server(self) -> bool:
        deadline = time.monotonic() + self.server_startup_timeout
        while time.monotonic() < deadline:
            process = self._server_process
            if process is None or process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"{self.server_url}/", timeout=0.5) as response:
                    if response.status == 200:
                        self._server_ready.set()
                        log.info("whisper-server pronto; modelo permanecerá carregado")
                        return True
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)
        self._server_ready.clear()
        log.warning("whisper-server não ficou pronto; mantendo fallback pelo CLI")
        return False

    def stop_server(self) -> None:
        with self._server_lock:
            process, self._server_process = self._server_process, None
            self._server_ready.clear()
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

    def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        if not self.available or not pcm:
            return ""
        with tempfile.TemporaryDirectory(prefix="zee-whisper-") as temp_dir:
            temp = Path(temp_dir)
            wav_path = temp / "comando.wav"
            output_prefix = temp / "transcricao"
            with wave.open(str(wav_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(int(sample_rate))
                wav_file.writeframes(pcm)

            if self.persistent:
                if not self.server_ready:
                    # Se a primeira pergunta chegar durante a carga inicial,
                    # aguarda o servidor em vez de carregar uma segunda cópia
                    # do modelo pelo CLI (importante nos 4 GB do Raspberry Pi).
                    self.start_server(blocking=True)
                if self.server_ready:
                    server_text = self._transcribe_server(wav_path)
                    if server_text:
                        log.info("transcrição whisper-server: %r", server_text)
                        return server_text

            command = [
                str(self.binary),
                "-m", str(self.model_path),
                "-f", str(wav_path),
                "-l", self.language,
                "-t", str(self.threads),
                "-nt", "-np", "-otxt",
                "-of", str(output_prefix),
            ]
            try:
                subprocess.run(
                    command,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.timeout_seconds,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                log.warning("whisper.cpp falhou; usando transcrição Vosk: %s", exc)
                return ""

            output_path = output_prefix.with_suffix(".txt")
            if not output_path.is_file():
                log.warning("whisper.cpp não gerou %s; usando Vosk", output_path)
                return ""
            text = " ".join(output_path.read_text(encoding="utf-8").split()).strip()
            log.info("transcrição whisper.cpp: %r", text)
            return text

    def _transcribe_server(self, wav_path: Path) -> str:
        boundary = f"----zee-{uuid.uuid4().hex}"
        wav_bytes = wav_path.read_bytes()
        body = bytearray()

        def add_field(name: str, value: str) -> None:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        add_field("response_format", "text")
        add_field("temperature", "0.0")
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            b'Content-Disposition: form-data; name="file"; filename="comando.wav"\r\n'
        )
        body.extend(b"Content-Type: audio/wav\r\n\r\n")
        body.extend(wav_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        request = urllib.request.Request(
            f"{self.server_url}/inference",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return " ".join(response.read().decode("utf-8").split()).strip()
        except (OSError, UnicodeError) as exc:
            log.warning("whisper-server falhou; tentando CLI: %s", exc)
            return ""


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


def result_hypotheses(payload: str) -> List[str]:
    """Todas as transcrições de um resultado do Vosk, da melhor para a pior.

    Com ``SetMaxAlternatives(n)`` o Vosk devolve ``{"alternatives": [...]}``
    em vez de ``{"text": ...}``; as duas formas são tratadas aqui.
    """
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []

    alternativas = data.get("alternatives")
    if isinstance(alternativas, list):
        textos = []
        for item in alternativas:
            if isinstance(item, dict):
                texto = str(item.get("text") or "").strip()
                if texto and texto not in textos:
                    textos.append(texto)
        return textos

    texto = str(data.get("text") or data.get("partial") or "").strip()
    return [texto] if texto else []


def result_text(payload: str) -> str:
    """Melhor transcrição de um resultado do Vosk (string vazia se não houver)."""
    hipoteses = result_hypotheses(payload)
    return hipoteses[0] if hipoteses else ""


class CommandRecognizer:
    """Estágio 2: grava até o usuário parar de falar e transcreve."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, sample_rate: int = 16000) -> None:
        self.sample_rate = int(sample_rate)
        self.configure(config or {})

    def configure(self, config: Dict[str, Any]) -> None:
        self.max_record_seconds = float(config.get("max_record_seconds", 12))
        self.min_record_seconds = float(config.get("min_record_seconds", 0.8))
        self.no_speech_timeout = float(config.get("no_speech_timeout_seconds", 10.0))
        self.silence_threshold = float(config.get("silence_rms_threshold", 350))
        self.silence_duration = float(config.get("silence_duration_seconds", 1.2))
        self.min_speech_blocks = max(1, int(config.get("min_speech_blocks", 2)))
        # N-best: o Vosk devolve várias transcrições e o matcher escolhe a que
        # faz sentido para o catálogo (a mais provável acusticamente nem sempre é).
        self.max_alternatives = max(1, int(config.get("max_alternatives", 3)))

    def configure_recognizer(self, recognizer) -> None:
        """Liga as alternativas N-best no reconhecedor de comandos."""
        if self.max_alternatives > 1:
            try:
                recognizer.SetMaxAlternatives(self.max_alternatives)
            except Exception as exc:  # pragma: no cover - versão antiga do vosk
                log.debug("SetMaxAlternatives indisponível: %s", exc)

    def capture(
        self,
        stream: MicrophoneStream,
        recognizer,
        activity_callback: Optional[Callable[[float, bool], None]] = None,
        transcriber: Optional[OfflineTranscriber] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Captura um comando.

        Devolve ``(melhor_texto, métricas)``; ``métricas["hypotheses"]`` traz
        todas as alternativas, na ordem de confiança do reconhecedor.
        """
        recognizer.Reset()
        started = time.time()
        speech_started = False
        consecutive_voice_blocks = 0
        last_voice = started
        peak = 0.0
        blocks = 0
        finals = []
        pcm = bytearray()
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
            pcm.extend(data)
            level = rms(data)
            peak = max(peak, level)
            now = time.time()
            is_speaking = level >= self.silence_threshold

            if is_speaking:
                consecutive_voice_blocks += 1
                if not speech_started and consecutive_voice_blocks >= self.min_speech_blocks:
                    log.debug("início de fala detectado (rms=%.0f)", level)
                    speech_started = True
                if speech_started:
                    last_voice = now
            else:
                consecutive_voice_blocks = 0

            if activity_callback is not None:
                try:
                    activity_callback(level, speech_started and is_speaking)
                except Exception as exc:  # feedback visual nunca interrompe a captura
                    log.debug("falha ao publicar atividade do microfone: %s", exc)

            if recognizer.AcceptWaveform(data):
                trecho = result_hypotheses(recognizer.Result())
                if trecho and speech_started:
                    finals.append(trecho)

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

        tail = result_hypotheses(recognizer.FinalResult())
        if tail and speech_started:
            finals.append(tail)

        # Cada bloco final tem N alternativas; combinamos por posição para
        # formar N frases completas ("melhor de cada", "segunda de cada"...).
        hypotheses: List[str] = []
        largura = max((len(bloco) for bloco in finals), default=0)
        for indice in range(largura):
            partes = [bloco[min(indice, len(bloco) - 1)] for bloco in finals if bloco]
            frase = " ".join(p for p in partes if p).strip()
            if frase and frase not in hypotheses:
                hypotheses.append(frase)
        text = hypotheses[0] if hypotheses else ""

        # O Vosk continua sendo alimentado durante a captura e funciona como
        # fallback. Quando instalado, o Whisper é preferido para a frase livre.
        whisper_text = ""
        if transcriber is not None and speech_started:
            whisper_text = transcriber.transcribe(bytes(pcm), self.sample_rate)
            if whisper_text:
                text = whisper_text
                hypotheses = [whisper_text, *[item for item in hypotheses if item != whisper_text]]

        metrics = {
            "duration": round(time.time() - started, 2),
            "blocks": blocks,
            "peak_rms": round(peak, 1),
            "speech_detected": speech_started,
            "stop_reason": reason,
            "hypotheses": hypotheses,
            "recognizer": "whisper.cpp" if whisper_text else ("vosk" if speech_started else "none"),
        }
        log.info("transcrição: %r (%s alternativas, %s)", text, len(hypotheses), metrics["stop_reason"])
        if len(hypotheses) > 1:
            log.debug("alternativas: %s", hypotheses[1:])
        return text, metrics
