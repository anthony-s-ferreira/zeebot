"""Efeitos sonoros do assistente e sua interação com a wakeword."""

from pathlib import Path

import pytest

from app.audio import AudioPlayer, SoundBoard
from app.state import State, StateMachine


class FakePlayer:
    """Player que só registra o que tocaria."""

    def __init__(self, ok: bool = True) -> None:
        self.tocados = []
        self.paradas = 0
        self.ok = ok
        self.command = ["fake"]

    def play(self, path, preempt: bool = False) -> bool:
        self.tocados.append((Path(path).name, preempt))
        return self.ok

    def stop(self) -> None:
        self.paradas += 1


@pytest.fixture
def sons(tmp_path):
    arquivos = {}
    for nome in ("saudacao", "pode-falar", "encontrei", "erro"):
        caminho = tmp_path / f"{nome}.mp3"
        caminho.write_bytes(b"fake mp3")
        arquivos[nome] = caminho
    return arquivos


@pytest.fixture
def board(sons, tmp_path):
    player = FakePlayer()
    board = SoundBoard(
        player,
        {
            "startup": str(sons["saudacao"]),
            "wakeword": str(sons["pode-falar"]),
            "found": str(sons["encontrei"]),
            "error": str(sons["erro"]),
        },
        resolver=lambda v: Path(v) if v else None,
    )
    board.player = player
    return board


class TestSoundBoard:
    def test_todos_os_momentos_configurados(self, board):
        assert set(board.NAMES) == {"startup", "wakeword", "found", "error"}
        for nome in board.NAMES:
            assert board.exists(nome), nome

    def test_toca_o_arquivo_certo(self, board):
        board.play("startup")
        board.play("wakeword")
        board.play("found")
        board.play("error")
        assert [nome for nome, _ in board.player.tocados] == [
            "saudacao.mp3", "pode-falar.mp3", "encontrei.mp3", "erro.mp3",
        ]

    def test_avisos_interrompem_o_anterior(self, board):
        board.play("found")
        assert board.player.tocados[0][1] is True     # preempt

    def test_nome_desconhecido_nao_quebra(self, board):
        assert board.play("inexistente") is False
        assert board.player.tocados == []

    def test_arquivo_ausente_nao_quebra(self, tmp_path):
        player = FakePlayer()
        board = SoundBoard(
            player, {"startup": str(tmp_path / "nao-existe.mp3")}, resolver=lambda v: Path(v) if v else None
        )
        assert board.exists("startup") is False
        assert board.play("startup") is False
        assert player.tocados == []

    def test_som_nao_configurado(self, tmp_path):
        board = SoundBoard(FakePlayer(), {}, resolver=lambda v: Path(v) if v else None)
        assert board.play("found") is False
        assert board.status()["found"] == {"path": None, "exists": False}

    def test_status(self, board, sons):
        status = board.status()
        assert status["wakeword"]["exists"] is True
        assert status["wakeword"]["path"].endswith("pode-falar.mp3")

    def test_stop_silencia(self, board):
        board.stop()
        assert board.player.paradas == 1


class TestSilencioDuranteOAudio:
    """O Zee não pode escutar a si mesmo pelo alto-falante."""

    def test_wakeword_suspensa_enquanto_toca(self, sons):
        state = StateMachine()
        state.set_microphone(True, "mic")
        state.set_model_loaded(True)
        state.set_state(State.HOME_LISTENING)
        assert state.wakeword_enabled is True

        board = SoundBoard(
            FakePlayer(),
            {"startup": str(sons["saudacao"])},
            resolver=lambda v: Path(v) if v else None,
            state=state,
            tail_silence=5.0,
        )

        estado_durante = {}

        def espiar(path, preempt=False):
            estado_durante["wakeword"] = state.wakeword_enabled
            return True

        board.player.play = espiar
        board.play("startup")

        assert estado_durante["wakeword"] is False      # mudo enquanto fala
        assert state.wakeword_enabled is False          # e no rabicho de silêncio
        assert state.snapshot()["audio_playing"] is False

    def test_snapshot_expoe_o_estado(self):
        state = StateMachine()
        state.set_audio_playing(True)
        assert state.snapshot()["audio_playing"] is True
        state.set_audio_playing(False)
        assert state.snapshot()["audio_playing"] is False


class TestAudioPlayer:
    def test_sem_player_disponivel(self, tmp_path):
        arquivo = tmp_path / "a.mp3"
        arquivo.write_bytes(b"x")
        player = AudioPlayer([["binario-que-nao-existe-xyz"]])
        assert player.available is False
        assert player.play(arquivo) is False

    def test_arquivo_inexistente(self, tmp_path):
        player = AudioPlayer([["binario-que-nao-existe-xyz"]])
        assert player.play(tmp_path / "nao-existe.mp3") is False
        assert player.play(None) is False

    def test_stop_sem_processo_nao_quebra(self):
        AudioPlayer([]).stop()
