"""Máquina de estados do Zee Assistant.

A regra crítica do produto vive aqui: a detecção de wakeword só pode estar
ativa em ``HOME_LISTENING``.  Qualquer outra tela (MENU, listagem, conteúdo,
configuração de Wi-Fi, erro) desliga o "Oi, Zee".
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Dict, Optional

from .events import EventBus

log = logging.getLogger(__name__)


class State(str, Enum):
    BOOTING = "BOOTING"
    WIFI_SETUP = "WIFI_SETUP"
    HOME_LISTENING = "HOME_LISTENING"
    WAKEWORD_DETECTED = "WAKEWORD_DETECTED"
    WAITING_USER = "WAITING_USER"
    PROCESSING_COMMAND = "PROCESSING_COMMAND"
    ANSWERING = "ANSWERING"
    MENU = "MENU"
    RESOURCE_LIST = "RESOURCE_LIST"
    RESOURCE_VIEW = "RESOURCE_VIEW"
    ERROR = "ERROR"

    def __str__(self) -> str:  # pragma: no cover - conveniência
        return self.value


#: Estados que fazem parte do ciclo iniciado pelo wakeword.
VOICE_CYCLE_STATES = {
    State.WAKEWORD_DETECTED,
    State.WAITING_USER,
    State.PROCESSING_COMMAND,
    State.ANSWERING,
}

#: Telas que o frontend pode pedir via /api/navigation.
VIEW_TO_STATE = {
    "home": State.HOME_LISTENING,
    "menu": State.MENU,
    "list": State.RESOURCE_LIST,
    "resource": State.RESOURCE_VIEW,
    "error": State.ERROR,
    "wifi": State.WIFI_SETUP,
}


class StateMachine:
    """Estado global observável, seguro para uso entre threads."""

    def __init__(self, bus: Optional[EventBus] = None) -> None:
        self.bus = bus or EventBus()
        self._lock = threading.RLock()
        self._state = State.BOOTING
        self._context: Dict[str, Any] = {}
        self._changed_at = time.time()
        self._wakeword_blocked_until = 0.0
        self._audio_playing = False
        self._mic_available = False
        self._mic_device: Optional[str] = None
        self._model_loaded = False
        self._voice_error: Optional[str] = None
        self._speech_recognizer: Dict[str, Any] = {
            "engine": None,
            "model": None,
            "label": "Inicializando...",
            "available": False,
            "fallback": False,
        }
        self._network: Dict[str, Any] = {"connected": False, "ssid": None, "ip": None}

    # ----------------------------------------------------------------- estado
    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    @property
    def context(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._context)

    def set_state(
        self,
        new_state: State,
        context: Optional[Dict[str, Any]] = None,
        reason: str = "",
        publish: bool = True,
    ) -> State:
        with self._lock:
            previous = self._state
            self._state = new_state
            self._context = dict(context or {})
            self._changed_at = time.time()
            snapshot = self._snapshot_locked()
        if previous != new_state:
            log.info(
                "estado: %s -> %s%s (wakeword=%s)",
                previous.value,
                new_state.value,
                f" [{reason}]" if reason else "",
                "on" if snapshot["wakeword_enabled"] else "off",
            )
        if publish:
            self.bus.publish("state", snapshot)
        return new_state

    def set_view(self, view: str, context: Optional[Dict[str, Any]] = None) -> State:
        """Traduz a tela informada pelo frontend em estado do backend."""
        target = VIEW_TO_STATE.get(str(view).lower())
        if target is None:
            raise ValueError(f"tela desconhecida: {view}")
        return self.set_state(target, context, reason=f"navegação:{view}")

    # -------------------------------------------------------------- wakeword
    @property
    def wakeword_enabled(self) -> bool:
        """Verdadeiro apenas na Home, em silêncio e fora do cooldown."""
        with self._lock:
            if self._state is not State.HOME_LISTENING:
                return False
            if not self._mic_available or not self._model_loaded:
                return False
            if self._audio_playing:
                return False
            return time.time() >= self._wakeword_blocked_until

    def set_audio_playing(self, playing: bool) -> None:
        """Suspende a wakeword enquanto o próprio Zee está falando."""
        with self._lock:
            if self._audio_playing == playing:
                return
            self._audio_playing = playing
        log.debug("áudio do assistente: %s", "tocando" if playing else "parado")

    @property
    def voice_cycle_active(self) -> bool:
        with self._lock:
            return self._state in VOICE_CYCLE_STATES

    def block_wakeword_for(self, seconds: float) -> None:
        """Cooldown curto para evitar redisparo imediato."""
        with self._lock:
            self._wakeword_blocked_until = max(
                self._wakeword_blocked_until, time.time() + max(0.0, seconds)
            )

    # ------------------------------------------------------------- capacidade
    def set_microphone(self, available: bool, device: Optional[str] = None) -> None:
        with self._lock:
            changed = self._mic_available != available or self._mic_device != device
            self._mic_available = available
            self._mic_device = device
        if changed:
            log.info("microfone: %s (%s)", "disponível" if available else "indisponível", device or "-")
            self.bus.publish("capabilities", self.snapshot())

    def set_model_loaded(self, loaded: bool, error: Optional[str] = None) -> None:
        with self._lock:
            self._model_loaded = loaded
            self._voice_error = error
        log.info("modelo Vosk: %s%s", "carregado" if loaded else "indisponível", f" ({error})" if error else "")
        self.bus.publish("capabilities", self.snapshot())

    def set_speech_recognizer(
        self,
        engine: Optional[str],
        model: Optional[str],
        available: bool = True,
        fallback: bool = False,
    ) -> None:
        """Informa qual motor/modelo transcreve os comandos do usuário."""
        engine_name = str(engine or "").strip()
        model_name = str(model or "").strip()
        if available and engine_name:
            label = f"{engine_name} {model_name}".strip()
        else:
            label = "Indisponível"
        recognizer = {
            "engine": engine_name or None,
            "model": model_name or None,
            "label": label,
            "available": bool(available),
            "fallback": bool(fallback),
        }
        with self._lock:
            changed = self._speech_recognizer != recognizer
            self._speech_recognizer = recognizer
        if changed:
            log.info("reconhecedor de comandos: %s", label)
            self.bus.publish("capabilities", self.snapshot())

    def set_network(self, connected: bool, ssid: Optional[str] = None, ip: Optional[str] = None) -> None:
        with self._lock:
            changed = self._network.get("connected") != connected or self._network.get("ssid") != ssid
            self._network = {"connected": connected, "ssid": ssid, "ip": ip}
        if changed:
            log.info("rede: %s ssid=%s ip=%s", "conectado" if connected else "desconectado", ssid, ip)
            self.bus.publish("network", {"network": dict(self._network)})

    # --------------------------------------------------------------- snapshot
    def _snapshot_locked(self) -> Dict[str, Any]:
        wakeword = (
            self._state is State.HOME_LISTENING
            and self._mic_available
            and self._model_loaded
            and not self._audio_playing
            and time.time() >= self._wakeword_blocked_until
        )
        return {
            "state": self._state.value,
            "context": dict(self._context),
            "changed_at": self._changed_at,
            "wakeword_enabled": wakeword,
            "audio_playing": self._audio_playing,
            "voice_cycle_active": self._state in VOICE_CYCLE_STATES,
            "microphone": {"available": self._mic_available, "device": self._mic_device},
            "voice_model": {"loaded": self._model_loaded, "error": self._voice_error},
            "speech_recognizer": dict(self._speech_recognizer),
            "network": dict(self._network),
        }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    # ---------------------------------------------------------------- eventos
    def publish(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.bus.publish(event_type, payload or {})
