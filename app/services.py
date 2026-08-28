"""Composição das partes do sistema (injeção de dependências manual)."""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from .audio import AudioPlayer
from .config import Config
from .events import EventBus
from .network.manager import NetworkSupervisor
from .resources import ResourceLibrary
from .state import State, StateMachine
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
        voice_cfg = self.config.section("voice")
        self.player = AudioPlayer(
            voice_cfg.get("audio_players", []),
            float(voice_cfg.get("audio_player_timeout_seconds", 15)),
        )
        self.voice = VoiceEngine(self.config, self.state, self.matcher, self.player)
        self.network = NetworkSupervisor(self.config, self.state)
        self._started = threading.Event()

    # ------------------------------------------------------------------ ciclo
    def start(self) -> None:
        if self._started.is_set():
            return
        self._started.set()
        log.info("iniciando serviços do Zee Assistant")
        self.voice.start()
        self.network.start()

    def stop(self) -> None:
        if not self._started.is_set():
            return
        log.info("encerrando serviços")
        try:
            self.voice.stop()
        finally:
            self.network.stop()
        self._started.clear()

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
            "network": snapshot["network"],
            "setup_mode": self.network.setup_mode,
            "resources": self.library.counts(),
            "resources_error": self.library.last_error,
            "audio_player": " ".join(self.player.command) if self.player.command else None,
            "ui": self.config.section("ui"),
            "thresholds": {
                "confidence": self.matcher.threshold,
                "ambiguity_margin": self.matcher.margin,
                "error_auto_return_seconds": self.config.get("app.error_auto_return_seconds", 5),
                "command_timeout_seconds": self.config.get("voice.command.max_record_seconds", 10),
            },
        }

    def go_home(self) -> State:
        """Volta para a Home reativando a wakeword."""
        return self.state.set_state(State.HOME_LISTENING, reason="navegação:home")
