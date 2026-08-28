"""Síntese local das respostas com Piper."""

import wave

from app.state import StateMachine
from app.tts import PiperTTS


class FakePlayer:
    available = True

    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def play(self, path, preempt=False, timeout=None):
        with wave.open(str(path), "rb") as wav_file:
            assert wav_file.getframerate() == 22050
            assert wav_file.readframes(1)
        self.calls.append((preempt, timeout))
        return self.result


class FakeVoice:
    def __init__(self):
        self.texts = []

    def synthesize_wav(self, text, wav_file, **_kwargs):
        self.texts.append(text)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 100)


def test_piper_sintetiza_e_reproduz_resposta(tmp_path):
    model = tmp_path / "pt_BR-faber-medium.onnx"
    model.touch()
    player = FakePlayer()
    state = StateMachine()
    tts = PiperTTS(
        {"model_path": str(model), "playback_timeout_seconds": 45}, player, state
    )
    voice = FakeVoice()
    tts._load_voice = lambda: voice

    assert tts.speak("  A resposta é vinte.  ") is True
    assert voice.texts == ["A resposta é vinte."]
    assert player.calls == [(True, 45.0)]
    assert state.snapshot()["audio_playing"] is False
    assert tts.last_error is None


def test_piper_indisponivel_mantem_resposta_na_tela(tmp_path):
    tts = PiperTTS(
        {"model_path": str(tmp_path / "voz-ausente.onnx")}, FakePlayer()
    )
    assert tts.available is False
    assert tts.speak("A resposta continua visível.") is False
    assert "não encontrada" in tts.last_error


def test_piper_ignora_texto_vazio(tmp_path):
    tts = PiperTTS({"model_path": str(tmp_path / "voz.onnx")}, FakePlayer())
    assert tts.speak("   ") is False


def test_piper_aquece_sem_reproduzir_audio(tmp_path):
    player = FakePlayer()
    tts = PiperTTS({"model_path": str(tmp_path / "voz.onnx")}, player)
    voice = FakeVoice()
    tts._load_voice = lambda: voice

    assert tts.warm_up() is True
    assert player.calls == []
    assert tts.last_error is None
