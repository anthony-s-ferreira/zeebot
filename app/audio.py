"""Detecção de microfone e reprodução de áudio local.

A frase "Oi, estou ouvindo." **precisa** vir de um MP3 local — nada de TTS.
A reprodução usa um player de linha de comando (mpg123 por padrão), que é o
caminho mais leve e confiável no Raspberry Pi.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .utils.proc import run, which

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- microfone
def list_input_devices() -> List[Dict[str, Any]]:
    """Lista dispositivos de entrada via sounddevice/PortAudio."""
    try:
        import sounddevice as sd  # import tardio: a app funciona sem áudio
    except Exception as exc:  # pragma: no cover - depende do SO
        log.warning("sounddevice indisponível (%s) — funções de voz desativadas", exc)
        return []

    devices: List[Dict[str, Any]] = []
    try:
        for index, device in enumerate(sd.query_devices()):
            if int(device.get("max_input_channels", 0)) > 0:
                devices.append(
                    {
                        "index": index,
                        "name": str(device.get("name", f"device {index}")),
                        "channels": int(device.get("max_input_channels", 0)),
                        "default_samplerate": float(device.get("default_samplerate", 0) or 0),
                    }
                )
    except Exception as exc:  # pragma: no cover - PortAudio pode falhar feio
        log.error("falha ao consultar dispositivos de áudio: %s", exc)
        return []
    return devices


def detect_microphone(preferred: Optional[Any] = None) -> Tuple[bool, Optional[str], Optional[Any]]:
    """Retorna ``(disponível, nome, índice)``.

    ``preferred`` pode ser o índice ou parte do nome do dispositivo desejado.
    Sem microfone o sistema continua utilizável pelo touchscreen.
    """
    devices = list_input_devices()
    if not devices:
        log.warning("nenhum microfone de entrada encontrado")
        return False, None, None

    if preferred is not None and str(preferred).strip() != "":
        wanted = str(preferred).strip().lower()
        for device in devices:
            if str(device["index"]) == wanted or wanted in device["name"].lower():
                log.info("microfone selecionado por configuração: %s", device["name"])
                return True, device["name"], device["index"]
        log.warning("dispositivo preferido %r não encontrado — usando o padrão", preferred)

    device = devices[0]
    try:
        import sounddevice as sd

        default_input = sd.default.device[0] if sd.default.device else None
        if default_input is not None and default_input >= 0:
            for candidate in devices:
                if candidate["index"] == default_input:
                    device = candidate
                    break
    except Exception:  # pragma: no cover
        pass

    log.info("microfone detectado: %s (índice %s)", device["name"], device["index"])
    return True, device["name"], device["index"]


def probe_microphone(index: Optional[Any], samplerate: int = 16000) -> bool:
    """Abre e fecha o dispositivo para confirmar que dá para capturar áudio."""
    try:
        import sounddevice as sd
    except Exception:
        return False
    try:
        stream = sd.RawInputStream(
            samplerate=samplerate, blocksize=1024, dtype="int16", channels=1, device=index
        )
        stream.start()
        stream.read(256)
        stream.stop()
        stream.close()
        return True
    except Exception as exc:
        log.error("microfone encontrado mas não foi possível capturar áudio: %s", exc)
        return False


# --------------------------------------------------------------------- playback
class AudioPlayer:
    """Reprodutor de arquivos locais baseado em processos externos."""

    def __init__(self, players: Sequence[Sequence[str]], timeout: float = 15.0) -> None:
        self.timeout = float(timeout)
        self._lock = threading.Lock()
        self.command: Optional[List[str]] = None
        for candidate in players or []:
            if candidate and which(str(candidate[0])):
                self.command = [str(part) for part in candidate]
                break
        if self.command:
            log.info("player de áudio: %s", " ".join(self.command))
        else:
            log.warning(
                "nenhum player de áudio encontrado (mpg123/mpv/ffplay/cvlc) — "
                "instale com: sudo apt install mpg123"
            )

    @property
    def available(self) -> bool:
        return self.command is not None

    def play(self, path: Optional[Path]) -> bool:
        """Reproduz de forma síncrona.  Nunca levanta exceção."""
        if path is None:
            return False
        path = Path(path)
        if not path.exists():
            log.warning("Welcome audio not found: %s", path)
            return False
        if not self.command:
            log.warning("áudio %s não reproduzido: nenhum player disponível", path.name)
            return False

        with self._lock:
            result = run([*self.command, str(path)], timeout=self.timeout)
        if result.ok:
            log.info("áudio reproduzido: %s", path.name)
            return True
        log.error("falha ao reproduzir %s (rc=%s): %s", path.name, result.returncode, result.stderr)
        return False

    def play_async(self, path: Optional[Path]) -> threading.Thread:
        thread = threading.Thread(target=self.play, args=(path,), daemon=True, name="zee-audio")
        thread.start()
        return thread
