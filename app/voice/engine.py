"""Motor de voz: thread única que orquestra os dois estágios.

Ciclo completo:

``HOME_LISTENING`` -> (wakeword) -> ``WAKEWORD_DETECTED`` -> MP3 local ->
``WAITING_USER`` -> captura -> ``PROCESSING_COMMAND`` -> busca -> ação.

Fora de ``HOME_LISTENING`` o microfone é **fechado**, não apenas ignorado.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..audio import AudioPlayer, detect_microphone, probe_microphone
from ..config import Config
from ..state import State, StateMachine
from .matcher import (
    STATUS_MULTIPLE,
    STATUS_NOT_FOUND,
    STATUS_OPEN,
    STATUS_OPEN_LIST,
    MatchResult,
    ResourceMatcher,
)
from .mic import MicrophoneStream, MicrophoneUnavailable
from .recognizer import CommandRecognizer, VoiceModelError, VoskEngine, result_text
from .wakeword import WakewordDetector

log = logging.getLogger(__name__)

IDLE_SLEEP = 0.2
MIC_RETRY_SECONDS = 15.0


class VoiceEngine:
    """Thread de voz.  Só toca no estado através da ``StateMachine``."""

    def __init__(
        self,
        config: Config,
        state: StateMachine,
        matcher: ResourceMatcher,
        player: Optional[AudioPlayer] = None,
    ) -> None:
        self.config = config
        self.state = state
        self.matcher = matcher

        voice_cfg = config.section("voice")
        self.enabled = bool(voice_cfg.get("enabled", True))
        self.sample_rate = int(voice_cfg.get("sample_rate", 16000))
        self.block_size = int(voice_cfg.get("block_size", 4000))
        self.preferred_device = voice_cfg.get("input_device")
        self.welcome_audio = Config.resolve_path(voice_cfg.get("welcome_audio"))

        self.player = player or AudioPlayer(
            voice_cfg.get("audio_players", []),
            float(voice_cfg.get("audio_player_timeout_seconds", 15)),
        )
        self.detector = WakewordDetector(voice_cfg.get("wakeword", {}))
        self.command_recognizer = CommandRecognizer(
            voice_cfg.get("command", {}), self.sample_rate
        )
        self.engine = VoskEngine(
            Config.resolve_path(voice_cfg.get("model_path")) or Path("models/vosk/pt-br"),
            self.sample_rate,
        )

        self._stream: Optional[MicrophoneStream] = None
        self._wake_recognizer = None
        self._command_recognizer_obj = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._mic_index: Optional[Any] = None
        self._next_mic_check = 0.0
        self.last_transcript = ""

    # ------------------------------------------------------------------ ciclo
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="zee-voice", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._close_stream()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------- inicialização
    def _init_microphone(self) -> bool:
        available, name, index = detect_microphone(self.preferred_device)
        if available and not probe_microphone(index, self.sample_rate):
            available, name = False, None
        self._mic_index = index if available else None
        self.state.set_microphone(available, name)
        self._next_mic_check = time.time() + MIC_RETRY_SECONDS
        return available

    def _init_model(self) -> bool:
        try:
            self.engine.load()
        except VoiceModelError as exc:
            log.error("voz desativada: %s", exc)
            self.state.set_model_loaded(False, str(exc))
            return False
        except Exception as exc:  # pragma: no cover - erro inesperado do Vosk
            log.exception("erro inesperado ao carregar o modelo Vosk")
            self.state.set_model_loaded(False, str(exc))
            return False
        self.state.set_model_loaded(True)
        return True

    def _ensure_recognizers(self) -> None:
        if self._wake_recognizer is None:
            self._wake_recognizer = self.engine.create_recognizer(self.detector.grammar)
        if self._command_recognizer_obj is None:
            self._command_recognizer_obj = self.engine.create_recognizer(None)

    # --------------------------------------------------------------- microfone
    def _open_stream(self) -> bool:
        if self._stream and self._stream.is_open:
            return True
        stream = MicrophoneStream(self.sample_rate, self.block_size, self._mic_index)
        try:
            stream.open()
        except MicrophoneUnavailable as exc:
            log.error("%s", exc)
            self.state.set_microphone(False, None)
            self._next_mic_check = time.time() + MIC_RETRY_SECONDS
            self._stream = None
            return False
        self._stream = stream
        return True

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    # ------------------------------------------------------------------- loop
    def _run(self) -> None:
        if not self.enabled:
            log.warning("reconhecimento de voz desativado por configuração")
            self.state.set_model_loaded(False, "desativado na configuração")
            self.state.set_microphone(False, None)
            return

        has_mic = self._init_microphone()
        has_model = self._init_model()
        if not has_model:
            log.warning("aplicação segue funcionando apenas pelo touchscreen")
            return
        if has_mic:
            try:
                self._ensure_recognizers()
            except Exception as exc:  # pragma: no cover
                log.exception("falha ao criar reconhecedores: %s", exc)
                self.state.set_model_loaded(False, str(exc))
                return

        log.info("motor de voz pronto (aguardando estado HOME_LISTENING)")

        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # pragma: no cover - a thread não pode morrer
                log.exception("erro no motor de voz — recuperando em 2s")
                self._close_stream()
                self._stop.wait(2.0)

    def _tick(self) -> None:
        state_snapshot = self.state.snapshot()
        if not state_snapshot["microphone"]["available"]:
            self._close_stream()
            if time.time() >= self._next_mic_check:
                if self._init_microphone():
                    self._ensure_recognizers()
            self._stop.wait(1.0)
            return

        if not self.state.wakeword_enabled:
            if self._stream is not None:
                log.debug("wakeword desativada (%s) — liberando microfone", self.state.state.value)
                self._close_stream()
                if self._wake_recognizer is not None:
                    self._wake_recognizer.Reset()
                self.detector.reset()
            self._stop.wait(IDLE_SLEEP)
            return

        if not self._open_stream():
            self._stop.wait(2.0)
            return

        try:
            data = self._stream.read()
        except MicrophoneUnavailable as exc:
            log.error("leitura falhou: %s", exc)
            self._close_stream()
            self.state.set_microphone(False, None)
            return

        if not data or self._wake_recognizer is None:
            return

        detected = False
        if self._wake_recognizer.AcceptWaveform(data):
            text = result_text(self._wake_recognizer.Result())
            detected = self.detector.matches(text)
        else:
            partial = result_text(self._wake_recognizer.PartialResult())
            if partial:
                detected = self.detector.matches(partial)

        if detected:
            self._wake_recognizer.Reset()
            self.run_interaction()

    # -------------------------------------------------------------- interação
    def run_interaction(self) -> None:
        """Executa o ciclo pós-wakeword (passos 1 a 8 da especificação)."""
        if not self._busy.acquire(blocking=False):
            log.debug("interação já em andamento — ignorando disparo")
            return
        try:
            # Passo 1: interrompe a detecção da wakeword.
            self.state.set_state(State.WAKEWORD_DETECTED, reason="wakeword")
            self._close_stream()

            # Passo 2: MP3 local obrigatório (sem TTS).
            self.player.play(self.welcome_audio)

            # Passo 3: interface muda para "Aguardando usuário...".
            self.state.set_state(State.WAITING_USER, reason="captura de comando")

            # Passo 4/5: captura + transcrição local.
            text = ""
            metrics: Dict[str, Any] = {}
            if self._open_stream():
                self._stream.flush(1)
                try:
                    self._ensure_recognizers()
                    text, metrics = self.command_recognizer.capture(
                        self._stream, self._command_recognizer_obj
                    )
                except MicrophoneUnavailable as exc:
                    log.error("captura abortada: %s", exc)
                finally:
                    self._close_stream()
            self.last_transcript = text
            self.state.publish("transcript", {"text": text, "metrics": metrics})

            # Passos 6/7/8: interpretar, buscar e abrir.
            self.handle_transcript(text)
        finally:
            self._busy.release()

    def handle_transcript(self, text: str) -> MatchResult:
        """Interpreta a transcrição e leva o sistema ao estado resultante."""
        self.state.set_state(
            State.PROCESSING_COMMAND, {"transcript": text}, reason="busca de conteúdo"
        )
        if not text.strip():
            self._finish_not_found("Não entendi. Pode repetir?", text)
            return MatchResult(text, "", None, STATUS_NOT_FOUND, [])

        result = self.matcher.search(text)
        payload = result.to_dict(self.matcher.max_suggestions)

        if result.status == STATUS_OPEN and result.best is not None:
            resource = result.best.resource
            self.state.set_state(
                State.RESOURCE_VIEW,
                {"resource_id": resource.id, "source": "voz"},
                reason=f"abrindo {resource.id}",
            )
            self.state.publish(
                "action",
                {"action": "open_resource", "resource_id": resource.id, "match": payload},
            )
        elif result.status == STATUS_MULTIPLE:
            self.state.set_state(
                State.RESOURCE_LIST,
                {"source": "voz", "mode": "options"},
                reason="múltiplas opções",
            )
            self.state.publish("action", {"action": "show_options", "match": payload})
        elif result.status == STATUS_OPEN_LIST:
            self.state.set_state(
                State.RESOURCE_LIST,
                {"tipo": result.detected_type, "source": "voz"},
                reason=f"listagem {result.detected_type}",
            )
            self.state.publish(
                "action",
                {"action": "open_list", "tipo": result.detected_type, "match": payload},
            )
        else:
            self._finish_not_found(
                self.config.get("ui.not_found_text", "Não encontrei esse conteúdo."), text, payload
            )
        return result

    def _finish_not_found(
        self, message: str, transcript: str, payload: Optional[Dict[str, Any]] = None
    ) -> None:
        self.state.set_state(
            State.ERROR, {"message": message, "transcript": transcript}, reason="não encontrado"
        )
        self.state.publish(
            "action", {"action": "not_found", "message": message, "match": payload or {}}
        )
        delay = float(self.config.get("app.error_auto_return_seconds", 5))
        threading.Timer(delay, self._return_home_if_error).start()

    def _return_home_if_error(self) -> None:
        if self.state.state is State.ERROR:
            self.state.block_wakeword_for(1.0)
            self.state.set_state(State.HOME_LISTENING, reason="retorno automático")
            self.state.publish("action", {"action": "go_home"})

    # ------------------------------------------------------------------ testes
    def simulate_command(self, text: str) -> MatchResult:
        """Executa o ciclo de interpretação sem microfone (usado nos testes)."""
        log.info("comando simulado: %r", text)
        self.last_transcript = text
        self.state.publish("transcript", {"text": text, "metrics": {"simulated": True}})
        return self.handle_transcript(text)

    def status(self) -> Dict[str, Any]:
        snapshot = self.state.snapshot()
        return {
            "enabled": self.enabled,
            "running": self.running,
            "model_loaded": self.engine.loaded,
            "model_path": str(self.engine.model_path),
            "microphone": snapshot["microphone"],
            "wakeword_enabled": snapshot["wakeword_enabled"],
            "wakeword_phrases": self.detector.phrases,
            "grammar": self.detector.grammar,
            "audio_player": " ".join(self.player.command) if self.player.command else None,
            "welcome_audio": str(self.welcome_audio) if self.welcome_audio else None,
            "welcome_audio_exists": bool(self.welcome_audio and self.welcome_audio.exists()),
            "last_transcript": self.last_transcript,
        }
