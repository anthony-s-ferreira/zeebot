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
from typing import Any, Dict, List, Optional

from ..audio import AudioPlayer, SoundBoard, detect_microphone, probe_microphone
from ..config import Config
from ..state import State, StateMachine
from .matcher import (
    STATUS_MULTIPLE,
    STATUS_NOT_FOUND,
    STATUS_OPEN,
    STATUS_OPEN_LIST,
    STATUS_OPEN_MENU,
    MatchResult,
    ResourceMatcher,
)
from .mic import MicrophoneStream, MicrophoneUnavailable
from .recognizer import (
    CommandRecognizer,
    VoiceModelError,
    VoskEngine,
    WhisperCppTranscriber,
    result_text,
)
from .wakeword import WakewordDetector
from ..slm import SLMUnavailable
from ..utils.text import normalize

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
        sounds_board: Optional[SoundBoard] = None,
        slm=None,
        tts=None,
    ) -> None:
        self.config = config
        self.state = state
        self.matcher = matcher
        self.slm = slm
        self.tts = tts

        voice_cfg = config.section("voice")
        self.enabled = bool(voice_cfg.get("enabled", True))
        self.sample_rate = int(voice_cfg.get("sample_rate", 16000))
        self.block_size = int(voice_cfg.get("block_size", 4000))
        self.preferred_device = voice_cfg.get("input_device")

        self.player = player or AudioPlayer(
            voice_cfg.get("audio_players", []),
            float(voice_cfg.get("audio_player_timeout_seconds", 15)),
        )
        sounds = dict(voice_cfg.get("sounds") or {})
        # Compatibilidade com a chave antiga "welcome_audio".
        if not sounds.get("wakeword") and voice_cfg.get("welcome_audio"):
            sounds["wakeword"] = voice_cfg["welcome_audio"]
        self.sounds = sounds_board or SoundBoard(
            self.player,
            sounds,
            resolver=Config.resolve_path,
            state=state,
            tail_silence=float(voice_cfg.get("sound_tail_silence_seconds", 0.4)),
        )
        self.welcome_audio = self.sounds.path("wakeword")
        self.detector = WakewordDetector(voice_cfg.get("wakeword", {}))
        self.command_recognizer = CommandRecognizer(
            voice_cfg.get("command", {}), self.sample_rate
        )
        whisper_cfg = dict(voice_cfg.get("command", {}).get("whisper") or {})
        whisper_binary = str(whisper_cfg.get("binary", "whisper-cli"))
        if "/" in whisper_binary:
            whisper_binary = str(Config.resolve_path(whisper_binary))
        self.command_transcriber = WhisperCppTranscriber(
            binary=whisper_binary,
            model_path=Config.resolve_path(
                whisper_cfg.get("model_path", "models/whisper/ggml-base-q5_1.bin")
            ) or Path("models/whisper/ggml-base-q5_1.bin"),
            language=str(whisper_cfg.get("language", "pt")),
            threads=int(whisper_cfg.get("threads", 3)),
            timeout_seconds=float(whisper_cfg.get("timeout_seconds", 30)),
            enabled=bool(whisper_cfg.get("enabled", True)),
            persistent=bool(whisper_cfg.get("persistent", True)),
            server_binary=str(
                Config.resolve_path(
                    whisper_cfg.get(
                        "server_binary", "tools/whisper.cpp/build/bin/whisper-server"
                    )
                )
            ),
            server_host=str(whisper_cfg.get("server_host", "127.0.0.1")),
            server_port=int(whisper_cfg.get("server_port", 8178)),
            server_startup_timeout=float(
                whisper_cfg.get("server_startup_timeout_seconds", 30)
            ),
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
        self.command_transcriber.stop_server()

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
            self.command_recognizer.configure_recognizer(self._command_recognizer_obj)

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
            self.state.set_speech_recognizer(None, None, available=False)
            self.state.set_model_loaded(False, "desativado na configuração")
            self.state.set_microphone(False, None)
            return

        has_mic = self._init_microphone()
        has_model = self._init_model()
        if not has_model:
            self.state.set_speech_recognizer(None, None, available=False)
            log.warning("aplicação segue funcionando apenas pelo touchscreen")
            return
        if self.command_transcriber.available:
            whisper_model = self.command_transcriber.model_path.stem.removeprefix("ggml-")
            self.state.set_speech_recognizer("Whisper", whisper_model)
            log.info("comandos serão transcritos pelo whisper.cpp")
            self.command_transcriber.start_server(blocking=False)
        else:
            self.state.set_speech_recognizer(
                "Vosk", self.engine.model_path.name, fallback=True
            )
            log.warning(
                "whisper.cpp ou modelo indisponível; comandos usarão o fallback Vosk"
            )
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
            if text:
                log.info("fala entendida (wakeword): %r", text)
            detected = self.detector.matches(text)
        else:
            partial = result_text(self._wake_recognizer.PartialResult())
            if partial:
                log.debug("fala parcial (wakeword): %r", partial)

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

            # Passo 2: o aviso termina antes de abrir o microfone. Isso impede
            # que o alto-falante do próprio Zee contamine a transcrição.
            self.sounds.play("wakeword", blocking=True)

            # Passo 3: abre o microfone somente depois do aviso curto.
            text = ""
            metrics: Dict[str, Any] = {}
            if self._open_stream():
                flush_blocks = int(
                    self.config.get("voice.command.pre_capture_flush_blocks", 1)
                )
                self._stream.flush(flush_blocks)
                self.state.set_state(State.WAITING_USER, reason="captura de comando")
                try:
                    self._ensure_recognizers()
                    text, metrics = self.command_recognizer.capture(
                        self._stream,
                        self._command_recognizer_obj,
                        self._publish_microphone_activity,
                        self.command_transcriber if self.command_transcriber.available else None,
                    )
                except MicrophoneUnavailable as exc:
                    log.error("captura abortada: %s", exc)
                finally:
                    self._publish_microphone_activity(0, False)
                    self._close_stream()
            else:
                log.warning("não foi possível abrir o microfone após o aviso")
            self.last_transcript = text
            log.info(
                "fala entendida (comando): %r | alternativas=%s",
                text,
                metrics.get("hypotheses", []),
            )
            self.state.publish("transcript", {"text": text, "metrics": metrics})

            if not metrics.get("speech_detected", False):
                self._return_to_wakeword_after_silence()
                return

            # Passos 6/7/8: interpretar, buscar e abrir.
            self.handle_transcript(text, metrics.get("hypotheses"))
        finally:
            self._busy.release()

    def _return_to_wakeword_after_silence(self) -> None:
        """Sem fala confirmada, volta à escuta da wakeword sem gerar comando."""
        log.info("nenhuma fala confirmada — retornando à espera da wakeword")
        self.state.block_wakeword_for(0.5)
        self.state.set_state(State.HOME_LISTENING, reason="tempo de fala esgotado")
        self.state.publish("action", {"action": "go_home", "reason": "no_speech"})

    def _publish_microphone_activity(self, rms_level: float, active: bool) -> None:
        """Envia à tela um nível leve e normalizado durante a captura do comando."""
        threshold = max(1.0, self.command_recognizer.silence_threshold)
        level = min(1.0, max(0.0, float(rms_level) / (threshold * 3.0)))
        self.state.publish(
            "microphone_activity",
            {"active": bool(active), "level": round(level, 2)},
        )

    def handle_transcript(
        self, text: str, hypotheses: Optional[List[str]] = None
    ) -> MatchResult:
        """Interpreta a transcrição e leva o sistema ao estado resultante."""
        self.state.set_state(
            State.PROCESSING_COMMAND, {"transcript": text}, reason="busca de conteúdo"
        )
        if not text.strip():
            self._finish_not_found("Não entendi. Pode repetir?", text)
            return MatchResult(text, "", None, STATUS_NOT_FOUND, [])

        candidatas = list(hypotheses or [])
        if text not in candidatas:
            candidatas.insert(0, text)
        result = self.matcher.search_best(candidatas)
        payload = result.to_dict(self.matcher.max_suggestions)

        if result.status == STATUS_OPEN and result.best is not None:
            self.sounds.play("found", blocking=False)
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
            self.sounds.play("found", blocking=False)
            self.state.set_state(
                State.RESOURCE_LIST,
                {"source": "voz", "mode": "options", "return_to": "home"},
                reason="múltiplas opções",
            )
            self.state.publish("action", {"action": "show_options", "match": payload})
        elif result.status == STATUS_OPEN_MENU:
            self.sounds.play("found", blocking=False)
            self.state.set_state(State.MENU, {"source": "voz"}, reason="menu por voz")
            self.state.publish("action", {"action": "open_menu", "match": payload})
        elif result.status == STATUS_OPEN_LIST:
            self.sounds.play("found", blocking=False)
            self.state.set_state(
                State.RESOURCE_LIST,
                {
                    "tipo": result.detected_type,
                    "source": "voz",
                    "return_to": "home",
                },
                reason=f"listagem {result.detected_type}",
            )
            self.state.publish(
                "action",
                {"action": "open_list", "tipo": result.detected_type, "match": payload},
            )
        else:
            self._answer_with_slm_or_not_found(text, payload)
        return result

    def _answer_with_slm_or_not_found(self, text: str, payload: Dict[str, Any]) -> None:
        if self.slm is None:
            self._finish_not_found(
                self.config.get("ui.not_found_text", "Não encontrei esse conteúdo."), text, payload
            )
            return
        try:
            corrected = self.matcher.corrected_query(text)
            prompt = text
            if corrected != normalize(text):
                prompt = corrected
                log.info("correção fonética: %r -> %r", text, prompt)
            answer = self.slm.answer(prompt)
        except SLMUnavailable as exc:
            log.warning("SLM indisponível; mantendo fallback de conteúdo: %s", exc)
            self._finish_not_found(
                self.config.get("ui.not_found_text", "Não encontrei esse conteúdo."), text, payload
            )
            return
        self.state.set_state(
            State.ANSWERING, {"answer": answer, "transcript": text}, reason="resposta do SLM"
        )
        self.state.publish(
            "action", {"action": "show_answer", "answer": answer, "transcript": text}
        )
        threading.Thread(
            target=self._speak_answer_and_return,
            args=(answer,),
            daemon=True,
            name="zee-resposta-retorno",
        ).start()

    def _speak_answer_and_return(self, answer: str) -> None:
        """Lê a resposta com Piper e mantém o texto visível durante a fala."""
        if self.tts is not None:
            self.tts.speak(answer)
        self._return_home_after_answer()

    def _return_home_after_answer(self) -> None:
        delay = float(self.config.get("app.answer_auto_return_seconds", 5))
        if delay > 0:
            time.sleep(delay)
        if self.state.state is State.ANSWERING:
            self.state.block_wakeword_for(0.5)
            self.state.set_state(State.HOME_LISTENING, reason="retorno após resposta")
            self.state.publish("action", {"action": "go_home"})

    def _finish_not_found(
        self, message: str, transcript: str, payload: Optional[Dict[str, Any]] = None
    ) -> None:
        self.state.set_state(
            State.ERROR, {"message": message, "transcript": transcript}, reason="não encontrado"
        )
        self.state.publish(
            "action", {"action": "not_found", "message": message, "match": payload or {}}
        )
        threading.Thread(
            target=self._announce_error_and_return, daemon=True, name="zee-erro"
        ).start()

    def _announce_error_and_return(self) -> None:
        """Toca o aviso de erro e só então volta para a Home.

        A espera considera a duração real do áudio: voltar antes do fim
        reativaria a wakeword com o alto-falante ainda falando.
        """
        delay = float(self.config.get("app.error_auto_return_seconds", 5))
        inicio = time.time()
        self.sounds.play("error", blocking=True)
        restante = delay - (time.time() - inicio)
        if restante > 0:
            time.sleep(restante)
        self._return_home_if_error()

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
            "sounds": self.sounds.status(),
            "command_recognizer": {
                "preferred": "whisper.cpp",
                "active": "whisper.cpp" if self.command_transcriber.available else "vosk",
                "whisper_available": self.command_transcriber.available,
                "whisper_model": str(self.command_transcriber.model_path),
                "whisper_binary": str(self.command_transcriber.binary or ""),
                "persistent": self.command_transcriber.persistent,
                "server_ready": self.command_transcriber.server_ready,
                "server_binary": str(self.command_transcriber.server_binary or ""),
            },
            "tts": self.tts.status() if self.tts is not None else {"available": False},
            "last_transcript": self.last_transcript,
        }
