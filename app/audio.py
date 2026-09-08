"""Detecção de microfone e reprodução de áudio local.

A frase "Oi, estou ouvindo." **precisa** vir de um MP3 local — nada de TTS.
A reprodução usa um player de linha de comando (mpg123 por padrão), que é o
caminho mais leve e confiável no Raspberry Pi.
"""

from __future__ import annotations

import logging
import subprocess
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
        self._process_lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self.command: Optional[List[str]] = None
        self.wav_command: Optional[List[str]] = None
        for candidate in players or []:
            if candidate and which(str(candidate[0])):
                self.command = [str(part) for part in candidate]
                break
        # mpg123 is suitable for the alert MP3s, but Piper produces PCM WAV.
        # Prefer ALSA's native WAV player for those files.
        for candidate in (("aplay", "-q"), ("paplay",)):
            if which(candidate[0]):
                self.wav_command = list(candidate)
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

    def play(
        self,
        path: Optional[Path],
        preempt: bool = False,
        timeout: Optional[float] = None,
    ) -> bool:
        """Reproduz de forma síncrona.  Nunca levanta exceção.

        Com ``preempt=True`` o áudio que estiver tocando é interrompido — um
        aviso novo é sempre mais relevante que o anterior.
        """
        if path is None:
            return False
        path = Path(path)
        if not path.exists():
            log.warning("Audio not found: %s", path)
            return False
        if not self.command:
            log.warning("áudio %s não reproduzido: nenhum player disponível", path.name)
            return False

        if preempt:
            self.stop()

        command = self.wav_command if path.suffix.lower() == ".wav" else self.command
        if command is None:
            log.warning("áudio %s não reproduzido: player WAV indisponível", path.name)
            return False

        with self._lock:
            try:
                process = subprocess.Popen(  # noqa: S603 - lista de argumentos, sem shell
                    [*command, str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except OSError as exc:
                log.error("não foi possível iniciar o player para %s: %s", path.name, exc)
                return False

            with self._process_lock:
                self._process = process
            try:
                _, stderr = process.communicate(
                    timeout=self.timeout if timeout is None else float(timeout)
                )
                returncode = process.returncode
            except subprocess.TimeoutExpired:
                limit = self.timeout if timeout is None else float(timeout)
                log.warning("áudio %s excedeu %.0fs — interrompendo", path.name, limit)
                process.kill()
                process.communicate()
                returncode, stderr = 124, "timeout"
            finally:
                with self._process_lock:
                    if self._process is process:
                        self._process = None

        if returncode == 0:
            log.info("áudio reproduzido: %s", path.name)
            return True
        if returncode in (-15, -9, 143, 137):  # interrompido por outro aviso
            log.debug("áudio %s interrompido", path.name)
            return False
        log.error("falha ao reproduzir %s (rc=%s): %s", path.name, returncode, (stderr or "").strip())
        return False

    def stop(self) -> None:
        """Interrompe o áudio que estiver tocando (se houver)."""
        with self._process_lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:  # pragma: no cover
                process.kill()
        except OSError:  # pragma: no cover
            pass

    def play_async(self, path: Optional[Path]) -> threading.Thread:
        thread = threading.Thread(target=self.play, args=(path,), daemon=True, name="zee-audio")
        thread.start()
        return thread


class SoundBoard:
    """Os efeitos sonoros do assistente, por momento do fluxo.

    ============  ===========================================================
    ``startup``   o assistente ficou pronto (a Home apareceu)
    ``wakeword``  o "Oi, Zee" foi reconhecido — pode falar
    ``found``     o pedido foi entendido e o conteúdo vai abrir
    ``error``     o pedido não foi entendido
    ============  ===========================================================

    Enquanto um som toca, a wakeword fica suspensa: o dispositivo não pode
    escutar a si mesmo pelo microfone.
    """

    NAMES = ("startup", "wakeword", "found", "error")

    def __init__(
        self,
        player: AudioPlayer,
        sounds: Optional[Dict[str, Any]] = None,
        resolver=None,
        state=None,
        tail_silence: float = 0.4,
    ) -> None:
        self.player = player
        self.state = state
        self.tail_silence = float(tail_silence)
        self._resolver = resolver or (lambda value: Path(str(value)) if value else None)
        self._paths: Dict[str, Optional[Path]] = {}
        self.configure(sounds or {})

    def configure(self, sounds: Dict[str, Any]) -> None:
        self._paths = {}
        for name in self.NAMES:
            path = self._resolver(sounds.get(name))
            self._paths[name] = path
            if path is None:
                log.info("som '%s' não configurado", name)
            elif not path.exists():
                log.warning("som '%s' não encontrado: %s", name, path)
            else:
                log.debug("som '%s': %s", name, path)

    def path(self, name: str) -> Optional[Path]:
        return self._paths.get(name)

    def exists(self, name: str) -> bool:
        path = self._paths.get(name)
        return bool(path and path.exists())

    def play(self, name: str, blocking: bool = True, preempt: bool = True) -> bool:
        """Toca um efeito.  Nunca levanta exceção e nunca trava o fluxo."""
        path = self._paths.get(name)
        if path is None:
            log.debug("som '%s' não configurado — seguindo sem áudio", name)
            return False
        if not path.exists():
            log.warning("%s not found: %s", name.capitalize(), path)
            return False

        if not blocking:
            threading.Thread(
                target=self.play, args=(name, True, preempt), daemon=True, name=f"zee-som-{name}"
            ).start()
            return True

        if self.state is not None:
            self.state.set_audio_playing(True)
        try:
            return self.player.play(path, preempt=preempt)
        finally:
            if self.state is not None:
                self.state.set_audio_playing(False)
                # Pequena folga para o eco do alto-falante não virar wakeword.
                self.state.block_wakeword_for(self.tail_silence)

    def stop(self) -> None:
        """Silencia imediatamente o assistente."""
        self.player.stop()
        if self.state is not None:
            self.state.set_audio_playing(False)

    def status(self) -> Dict[str, Any]:
        return {
            name: {
                "path": str(self._paths[name]) if self._paths.get(name) else None,
                "exists": self.exists(name),
            }
            for name in self.NAMES
        }
