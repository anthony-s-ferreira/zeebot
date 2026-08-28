"""Captura de áudio do microfone (PortAudio via sounddevice)."""

from __future__ import annotations

import array
import logging
import math
from typing import Optional

log = logging.getLogger(__name__)


def rms(data: bytes) -> float:
    """RMS de um bloco PCM 16 bits mono — usado na detecção de silêncio."""
    if not data:
        return 0.0
    usable = len(data) - (len(data) % 2)
    samples = array.array("h")
    try:
        samples.frombytes(data[:usable])
    except ValueError:  # pragma: no cover - bloco malformado
        return 0.0
    if not samples:
        return 0.0
    total = 0
    for sample in samples:
        total += sample * sample
    return math.sqrt(total / len(samples))


class MicrophoneUnavailable(RuntimeError):
    """Erro amigável quando não há captura possível."""


class MicrophoneStream:
    """Abre/fecha o stream de entrada de forma explícita.

    O stream é fechado sempre que a wakeword é desativada ou durante a
    reprodução do MP3, liberando o dispositivo (requisito de performance).
    """

    def __init__(
        self,
        samplerate: int = 16000,
        blocksize: int = 4000,
        device: Optional[object] = None,
    ) -> None:
        self.samplerate = int(samplerate)
        self.blocksize = int(blocksize)
        self.device = device
        self._stream = None

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    def open(self) -> None:
        if self._stream is not None:
            return
        try:
            import sounddevice as sd
        except Exception as exc:  # pragma: no cover
            raise MicrophoneUnavailable(f"sounddevice indisponível: {exc}") from exc
        try:
            stream = sd.RawInputStream(
                samplerate=self.samplerate,
                blocksize=self.blocksize,
                dtype="int16",
                channels=1,
                device=self.device,
            )
            stream.start()
        except Exception as exc:
            raise MicrophoneUnavailable(f"não foi possível abrir o microfone: {exc}") from exc
        self._stream = stream
        log.debug("microfone aberto (%s Hz, bloco %s)", self.samplerate, self.blocksize)

    def read(self) -> bytes:
        """Lê um bloco.  Retorna ``b""`` em caso de falha recuperável."""
        if self._stream is None:
            raise MicrophoneUnavailable("stream fechado")
        try:
            data, overflowed = self._stream.read(self.blocksize)
        except Exception as exc:
            raise MicrophoneUnavailable(f"erro de leitura do microfone: {exc}") from exc
        if overflowed:
            log.debug("overflow de áudio (bloco descartado parcialmente)")
        return bytes(data)

    def flush(self, blocks: int = 2) -> None:
        """Descarta blocos residuais (ex.: eco do MP3 de boas-vindas)."""
        for _ in range(max(0, blocks)):
            try:
                self.read()
            except MicrophoneUnavailable:
                return

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
            log.debug("microfone liberado")
        except Exception as exc:  # pragma: no cover
            log.debug("erro ao fechar microfone: %s", exc)

    def __enter__(self) -> "MicrophoneStream":
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
