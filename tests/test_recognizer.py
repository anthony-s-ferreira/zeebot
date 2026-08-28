"""Leitura dos resultados do Vosk (sem precisar do modelo)."""

import json
from pathlib import Path

from app.voice.recognizer import (
    CommandRecognizer,
    WhisperCppTranscriber,
    is_valid_model_dir,
    result_hypotheses,
    result_text,
)


class TestLeituraDeResultados:
    def test_formato_simples(self):
        payload = json.dumps({"text": "quero ouvir o podcast"})
        assert result_text(payload) == "quero ouvir o podcast"
        assert result_hypotheses(payload) == ["quero ouvir o podcast"]

    def test_formato_parcial(self):
        assert result_text(json.dumps({"partial": "oi zé"})) == "oi zé"

    def test_formato_com_alternativas(self):
        payload = json.dumps(
            {
                "alternatives": [
                    {"text": "quero ouvir o pode se", "confidence": 201.9},
                    {"text": "quero ouvir o podcast", "confidence": 201.6},
                    {"text": "", "confidence": 200.0},
                ]
            }
        )
        assert result_hypotheses(payload) == ["quero ouvir o pode se", "quero ouvir o podcast"]
        assert result_text(payload) == "quero ouvir o pode se"

    def test_remove_duplicatas(self):
        payload = json.dumps({"alternatives": [{"text": "oi"}, {"text": "oi"}]})
        assert result_hypotheses(payload) == ["oi"]

    def test_entradas_invalidas(self):
        for payload in ["", "não é json", json.dumps([1, 2]), json.dumps({"text": ""})]:
            assert result_hypotheses(payload) == []
            assert result_text(payload) == ""


class TestConfiguracaoDaCaptura:
    def test_alternativas_configuraveis(self):
        assert CommandRecognizer({"max_alternatives": 5}).max_alternatives == 5
        assert CommandRecognizer({"max_alternatives": 0}).max_alternatives == 1
        assert CommandRecognizer({}).max_alternatives == 3

    def test_configure_recognizer_tolera_api_antiga(self):
        class Antigo:
            pass

        CommandRecognizer({"max_alternatives": 3}).configure_recognizer(Antigo())  # não levanta

    def test_configure_recognizer_liga_alternativas(self):
        class Fake:
            def __init__(self):
                self.n = None

            def SetMaxAlternatives(self, valor):  # noqa: N802 - API do vosk
                self.n = valor

        fake = Fake()
        CommandRecognizer({"max_alternatives": 4}).configure_recognizer(fake)
        assert fake.n == 4

    def test_uma_alternativa_nao_chama_a_api(self):
        class Fake:
            def SetMaxAlternatives(self, valor):  # noqa: N802
                raise AssertionError("não deveria ser chamado")

        CommandRecognizer({"max_alternatives": 1}).configure_recognizer(Fake())

    def test_whisper_substitui_transcricao_vosk(self):
        class Stream:
            def read(self):
                return int(1000).to_bytes(2, "little", signed=True) * 400

        class VoskFake:
            def Reset(self):
                pass

            def AcceptWaveform(self, _data):
                return False

            def FinalResult(self):
                return json.dumps({"text": "moldes"})

        class WhisperFake:
            def transcribe(self, pcm, sample_rate):
                assert pcm
                assert sample_rate == 16000
                return "quanto é dez mais dez"

        recognizer = CommandRecognizer(
            {
                "silence_rms_threshold": 350,
                "min_record_seconds": 0,
                "silence_duration_seconds": 0,
            }
        )
        text, metrics = recognizer.capture(Stream(), VoskFake(), transcriber=WhisperFake())
        assert text == "quanto é dez mais dez"
        assert metrics["recognizer"] == "whisper.cpp"
        assert "moldes" in metrics["hypotheses"]

    def test_silencio_descarta_alucinacao_dos_reconhecedores(self):
        class Stream:
            def read(self):
                return b"\x00\x00" * 400

        class VoskFake:
            def Reset(self):
                pass

            def AcceptWaveform(self, _data):
                return False

            def FinalResult(self):
                return json.dumps({"text": "lista de audios"})

        class WhisperFake:
            def transcribe(self, _pcm, _sample_rate):
                raise AssertionError("Whisper não deve receber silêncio")

        recognizer = CommandRecognizer(
            {"no_speech_timeout_seconds": 0, "max_record_seconds": 1}
        )
        text, metrics = recognizer.capture(
            Stream(), VoskFake(), transcriber=WhisperFake()
        )
        assert text == ""
        assert metrics["speech_detected"] is False
        assert metrics["hypotheses"] == []
        assert metrics["recognizer"] == "none"
        assert metrics["stop_reason"] == "nenhuma fala detectada"

    def test_um_pico_de_ruido_nao_conta_como_fala(self):
        class Stream:
            def read(self):
                return int(1000).to_bytes(2, "little", signed=True) * 400

        class VoskFake:
            def Reset(self):
                pass

            def AcceptWaveform(self, _data):
                return False

            def FinalResult(self):
                return json.dumps({"text": "lista de audios"})

        recognizer = CommandRecognizer(
            {
                "no_speech_timeout_seconds": 0,
                "max_record_seconds": 1,
                "min_speech_blocks": 2,
            }
        )
        text, metrics = recognizer.capture(Stream(), VoskFake())
        assert text == ""
        assert metrics["speech_detected"] is False


class TestWhisperCpp:
    def test_gera_wav_e_le_resultado(self, tmp_path, monkeypatch):
        binary = tmp_path / "whisper-cli"
        model = tmp_path / "ggml-base-q5_1.bin"
        binary.touch()
        binary.chmod(0o755)
        model.touch()

        def fake_run(command, **_kwargs):
            output_prefix = Path(command[command.index("-of") + 1])
            output_prefix.with_suffix(".txt").write_text(
                " Quanto é dez mais dez? \n", encoding="utf-8"
            )

        monkeypatch.setattr("app.voice.recognizer.subprocess.run", fake_run)
        transcriber = WhisperCppTranscriber(str(binary), model)
        result = transcriber.transcribe(b"\x00\x00" * 400, 16000)
        assert result == "Quanto é dez mais dez?"
        assert transcriber.available is True

    def test_indisponivel_retorna_vazio(self, tmp_path):
        transcriber = WhisperCppTranscriber(
            str(tmp_path / "binario-ausente"), tmp_path / "modelo-ausente.bin"
        )
        assert transcriber.available is False
        assert transcriber.transcribe(b"audio", 16000) == ""

    def test_envia_wav_para_servidor_persistente(self, tmp_path, monkeypatch):
        binary = tmp_path / "whisper-cli"
        server = tmp_path / "whisper-server"
        model = tmp_path / "ggml-base-q5_1.bin"
        for executable in (binary, server):
            executable.touch()
            executable.chmod(0o755)
        model.touch()
        wav_path = tmp_path / "comando.wav"
        wav_path.write_bytes(b"RIFF-audio-do-teste")
        captured = {}

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"quanto e dez mais dez"

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return Response()

        monkeypatch.setattr("app.voice.recognizer.urllib.request.urlopen", fake_urlopen)
        transcriber = WhisperCppTranscriber(
            str(binary), model, server_binary=str(server), timeout_seconds=12
        )

        assert transcriber._transcribe_server(wav_path) == "quanto e dez mais dez"
        request = captured["request"]
        assert request.full_url == "http://127.0.0.1:8178/inference"
        assert request.method == "POST"
        assert b'form-data; name="response_format"' in request.data
        assert b"RIFF-audio-do-teste" in request.data
        assert captured["timeout"] == 12


class TestFormatoDoModelo:
    def test_modelo_plano(self, tmp_path):
        (tmp_path / "final.mdl").touch()
        (tmp_path / "ivector").mkdir()
        assert is_valid_model_dir(tmp_path) is True

    def test_modelo_com_subpastas(self, tmp_path):
        (tmp_path / "am").mkdir()
        (tmp_path / "am" / "final.mdl").touch()
        assert is_valid_model_dir(tmp_path) is True

    def test_pasta_invalida(self, tmp_path):
        (tmp_path / "leiame.txt").touch()
        assert is_valid_model_dir(tmp_path) is False
