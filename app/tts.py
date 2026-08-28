"""Síntese de voz local das respostas usando Piper."""

from __future__ import annotations

import logging
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, Dict, Optional

from .audio import AudioPlayer
from .config import Config

log = logging.getLogger(__name__)


class PiperTTS:
    """Carrega uma voz Piper sob demanda e lê respostas em português."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]],
        player: AudioPlayer,
        state=None,
    ) -> None:
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.model_path = Config.resolve_path(
            config.get("model_path", "models/piper/pt_BR-faber-medium.onnx")
        ) or Path("models/piper/pt_BR-faber-medium.onnx")
        self.length_scale = float(config.get("length_scale", 1.0))
        self.volume = float(config.get("volume", 1.0))
        self.playback_timeout = float(config.get("playback_timeout_seconds", 60))
        self.player = player
        self.state = state
        self._voice = None
        self._load_lock = threading.Lock()
        self._speak_lock = threading.Lock()
        self.last_error: Optional[str] = None

    @property
    def available(self) -> bool:
        if not self.enabled or not self.model_path.is_file():
            return False
        try:
            import piper  # noqa: F401 - verificação tardia da dependência
        except ImportError:
            return False
        return self.player.available

    def _load_voice(self):
        if self._voice is not None:
            return self._voice
        if not self.enabled:
            raise RuntimeError("Piper TTS desativado na configuração")
        if not self.model_path.is_file():
            raise RuntimeError(f"voz Piper não encontrada: {self.model_path}")
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise RuntimeError("piper-tts não instalado") from exc
        with self._load_lock:
            if self._voice is None:
                log.info("carregando voz Piper: %s", self.model_path)
                self._voice = PiperVoice.load(self.model_path)
        return self._voice

    def speak(self, text: str) -> bool:
        """Sintetiza e reproduz uma resposta. Nunca propaga falhas ao fluxo."""
        clean_text = " ".join(str(text or "").split()).strip()
        if not clean_text:
            return False
        with self._speak_lock:
            if self.state is not None:
                self.state.set_audio_playing(True)
            try:
                voice = self._load_voice()
                try:
                    from piper import SynthesisConfig

                    synthesis_config = SynthesisConfig(
                        length_scale=self.length_scale,
                        volume=self.volume,
                    )
                except (ImportError, TypeError):
                    synthesis_config = None

                with tempfile.TemporaryDirectory(prefix="zee-piper-") as temp_dir:
                    wav_path = Path(temp_dir) / "resposta.wav"
                    with wave.open(str(wav_path), "wb") as wav_file:
                        if synthesis_config is None:
                            voice.synthesize_wav(clean_text, wav_file)
                        else:
                            voice.synthesize_wav(
                                clean_text, wav_file, syn_config=synthesis_config
                            )
                    played = self.player.play(
                        wav_path, preempt=True, timeout=self.playback_timeout
                    )
                self.last_error = None if played else "falha na reprodução do áudio"
                return played
            except Exception as exc:
                self.last_error = str(exc)
                log.warning("não foi possível ler a resposta com Piper: %s", exc)
                return False
            finally:
                if self.state is not None:
                    self.state.set_audio_playing(False)
                    self.state.block_wakeword_for(0.5)

    def warm_up(self) -> bool:
        """Carrega a voz ONNX antecipadamente, sem reproduzir áudio."""
        try:
            self._load_voice()
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("não foi possível aquecer o Piper: %s", exc)
            return False

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "model_path": str(self.model_path),
            "voice": self.model_path.stem,
            "loaded": self._voice is not None,
            "last_error": self.last_error,
        }
