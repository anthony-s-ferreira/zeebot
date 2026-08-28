"""Composição das partes do sistema (injeção de dependências manual)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from .audio import AudioPlayer, SoundBoard
from .config import Config
from .events import EventBus
from .network.manager import NetworkSupervisor
from .resources import ResourceLibrary
from .slm import LocalSLM
from .state import State, StateMachine
from .tts import PiperTTS
from .voice.engine import VoiceEngine
from .voice.matcher import ResourceMatcher

log = logging.getLogger(__name__)


class ZeeServices:
    """Mantém as instâncias de longa duração e o ciclo de vida delas."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()
        self.bus = EventBus()
        self.state = StateMachine(self.bus)

        resources_path = Config.resolve_path(self.config.get("app.resources_file", "data/recursos.json"))
        self.library = ResourceLibrary(
            resources_path, bool(self.config.get("app.auto_reload_resources", True))
        )
        self.matcher = ResourceMatcher(self.library, self.config.section("matching"))
        self.slm = LocalSLM(self.config.section("slm"))
        voice_cfg = self.config.section("voice")
        self.player = AudioPlayer(
            voice_cfg.get("audio_players", []),
            float(voice_cfg.get("audio_player_timeout_seconds", 15)),
        )
        sounds = dict(voice_cfg.get("sounds") or {})
        if not sounds.get("wakeword") and voice_cfg.get("welcome_audio"):
            sounds["wakeword"] = voice_cfg["welcome_audio"]
        self.sounds = SoundBoard(
            self.player,
            sounds,
            resolver=Config.resolve_path,
            state=self.state,
            tail_silence=float(voice_cfg.get("sound_tail_silence_seconds", 0.4)),
        )
        self.tts = PiperTTS(self.config.section("tts"), self.player, self.state)
        self.voice = VoiceEngine(
            self.config,
            self.state,
            self.matcher,
            self.player,
            self.sounds,
            self.slm,
            self.tts,
        )
        self.network = NetworkSupervisor(self.config, self.state)
        self._started = threading.Event()
        self._startup_sound_played = threading.Event()
        self._warmup_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ ciclo
    def start(self) -> None:
        if self._started.is_set():
            return
        self._started.set()
        log.info("iniciando serviços do Zee Assistant")
        self.voice.start()
        self.network.start()
        self._warmup_thread = threading.Thread(
            target=self._warm_models_when_ready,
            daemon=True,
            name="zee-model-warmup",
        )
        self._warmup_thread.start()

    def stop(self) -> None:
        if not self._started.is_set():
            return
        log.info("encerrando serviços")
        self._started.clear()
        self.sounds.stop()
        try:
            self.voice.stop()
        finally:
            self.network.stop()

    def _warm_models_when_ready(self) -> None:
        """Aquece Qwen e Piper quando a Home estiver estável e ociosa."""
        config = self.config.section("warmup")
        if not bool(config.get("enabled", True)):
            return
        delay = max(0.0, float(config.get("delay_seconds", 5)))
        stable_since: Optional[float] = None
        while self._started.is_set():
            snapshot = self.state.snapshot()
            idle = snapshot["state"] == State.HOME_LISTENING.value and not snapshot.get(
                "audio_playing", False
            )
            if idle:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= delay:
                    break
            else:
                stable_since = None
            time.sleep(0.25)
        if not self._started.is_set():
            return

        log.info("aquecendo modelos locais em segundo plano")
        if bool(config.get("slm", True)):
            self.slm.warm_up()
        if bool(config.get("tts", True)):
            # Se o usuário iniciou uma interação durante o Qwen, aguarda a Home
            # antes de consumir CPU com o carregamento do Piper.
            while self._started.is_set() and self.state.state is not State.HOME_LISTENING:
                time.sleep(0.25)
            if self._started.is_set():
                self.tts.warm_up()

    def _play_startup_sound_when_ready(self) -> None:
        """Toca a saudação quando o assistente fica pronto (a Home aparece).

        Espera o primeiro ``HOME_LISTENING`` — assim a saudação não toca
        durante a configuração de Wi-Fi, e toca certinho depois dela.
        """
        if not self.sounds.exists("startup"):
            return
        if self.state.state is State.HOME_LISTENING:
            self._emit_startup_sound()
            return

        subscriber = self.bus.subscribe()
        try:
            while not self._startup_sound_played.is_set():
                event = subscriber.get(timeout=2.0)
                if event is None:
                    if self.state.state is State.HOME_LISTENING:
                        self._emit_startup_sound()
                    continue
                data = event.get("data") or {}
                if event.get("type") == "state" and data.get("state") == State.HOME_LISTENING.value:
                    self._emit_startup_sound()
        finally:
            self.bus.unsubscribe(subscriber)

    def _emit_startup_sound(self) -> None:
        if self._startup_sound_played.is_set():
            return
        self._startup_sound_played.set()
        log.info("assistente pronto — tocando a saudação")
        self.sounds.play("startup", blocking=True)

    # ---------------------------------------------------------------- consulta
    def status(self) -> Dict[str, Any]:
        snapshot = self.state.snapshot()
        return {
            "version": self.config.get("app.version", "1.0.0"),
            "state": snapshot["state"],
            "context": snapshot["context"],
            "wakeword_enabled": snapshot["wakeword_enabled"],
            "microphone": snapshot["microphone"],
            "voice_model": snapshot["voice_model"],
            "speech_recognizer": snapshot["speech_recognizer"],
            "network": snapshot["network"],
            "setup_mode": self.network.setup_mode,
            "resources": self.library.counts(),
            "resources_error": self.library.last_error,
            "audio_player": " ".join(self.player.command) if self.player.command else None,
            "sounds": self.sounds.status(),
            "audio_playing": snapshot.get("audio_playing", False),
            "ui": self.config.section("ui"),
            "thresholds": {
                "confidence": self.matcher.threshold,
                "ambiguity_margin": self.matcher.margin,
                "error_auto_return_seconds": self.config.get("app.error_auto_return_seconds", 5),
                "command_timeout_seconds": self.config.get("voice.command.max_record_seconds", 10),
            },
            "slm": {
                "enabled": self.slm.enabled,
                "model_path": str(self.slm.model_path),
                "loaded": self.slm._model is not None,
            },
            "tts": self.tts.status(),
        }

    def go_home(self) -> State:
        """Volta para a Home reativando a wakeword."""
        return self.state.set_state(State.HOME_LISTENING, reason="navegação:home")
