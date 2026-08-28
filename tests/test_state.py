"""Máquina de estados — a regra crítica do wakeword."""

import time

import pytest

from app.state import State, StateMachine


@pytest.fixture
def machine():
    machine = StateMachine()
    machine.set_microphone(True, "Mic de teste")
    machine.set_model_loaded(True)
    return machine


class TestRegraDoWakeword:
    def test_home_habilita(self, machine):
        machine.set_state(State.HOME_LISTENING)
        assert machine.wakeword_enabled is True

    @pytest.mark.parametrize(
        "estado",
        [
            State.MENU,
            State.RESOURCE_LIST,
            State.RESOURCE_VIEW,
            State.WIFI_SETUP,
            State.ERROR,
            State.BOOTING,
            State.WAKEWORD_DETECTED,
            State.WAITING_USER,
            State.PROCESSING_COMMAND,
        ],
    )
    def test_demais_estados_desabilitam(self, machine, estado):
        machine.set_state(estado)
        assert machine.wakeword_enabled is False, estado

    def test_ciclo_de_voz_permanece_ativo(self, machine):
        for estado in (State.WAKEWORD_DETECTED, State.WAITING_USER, State.PROCESSING_COMMAND):
            machine.set_state(estado)
            assert machine.voice_cycle_active is True
        machine.set_state(State.MENU)
        assert machine.voice_cycle_active is False

    def test_fluxo_menu_e_volta_para_home(self, machine):
        machine.set_view("home")
        assert machine.wakeword_enabled is True
        machine.set_view("menu")          # regra: MENU desliga imediatamente
        assert machine.wakeword_enabled is False
        machine.set_view("list", {"tipo": "video"})
        assert machine.wakeword_enabled is False
        machine.set_view("resource", {"resource_id": "rec_001"})
        assert machine.wakeword_enabled is False
        machine.set_view("list", {"tipo": "video"})   # voltar do conteúdo: continua off
        assert machine.wakeword_enabled is False
        machine.set_view("home")                      # voltar para a Home: reativa
        assert machine.wakeword_enabled is True

    def test_sem_microfone_nunca_habilita(self, machine):
        machine.set_microphone(False, None)
        machine.set_state(State.HOME_LISTENING)
        assert machine.wakeword_enabled is False

    def test_sem_modelo_nunca_habilita(self, machine):
        machine.set_model_loaded(False, "modelo ausente")
        machine.set_state(State.HOME_LISTENING)
        assert machine.wakeword_enabled is False

    def test_cooldown_suspende_temporariamente(self, machine):
        machine.set_state(State.HOME_LISTENING)
        machine.block_wakeword_for(0.3)
        assert machine.wakeword_enabled is False
        time.sleep(0.35)
        assert machine.wakeword_enabled is True


class TestNavegacao:
    def test_tela_invalida(self, machine):
        with pytest.raises(ValueError):
            machine.set_view("tela-que-nao-existe")

    def test_contexto_preservado(self, machine):
        machine.set_view("resource", {"resource_id": "rec_002"})
        assert machine.context["resource_id"] == "rec_002"


class TestEventos:
    def test_mudanca_de_estado_publica_evento(self, machine):
        subscriber = machine.bus.subscribe()
        machine.set_state(State.MENU)
        event = subscriber.get(timeout=1.0)
        assert event is not None
        assert event["type"] == "state"
        assert event["data"]["state"] == "MENU"
        assert event["data"]["wakeword_enabled"] is False
        machine.bus.unsubscribe(subscriber)

    def test_reconhecedor_de_voz_aparece_no_snapshot(self, machine):
        machine.set_speech_recognizer("Whisper", "base-q5_1")
        recognizer = machine.snapshot()["speech_recognizer"]
        assert recognizer["label"] == "Whisper base-q5_1"
        assert recognizer["available"] is True
        assert recognizer["fallback"] is False

    def test_reconhecedor_fallback_e_publicado(self, machine):
        subscriber = machine.bus.subscribe()
        machine.set_speech_recognizer("Vosk", "pt-br", fallback=True)
        event = subscriber.get(timeout=1.0)
        assert event["type"] == "capabilities"
        assert event["data"]["speech_recognizer"]["fallback"] is True
        machine.bus.unsubscribe(subscriber)

    def test_assinante_lento_nao_bloqueia(self, machine):
        subscriber = machine.bus.subscribe()
        for _ in range(200):  # muito além do tamanho da fila
            machine.set_state(State.MENU)
            machine.set_state(State.HOME_LISTENING)
        assert subscriber.get(timeout=1.0) is not None
        machine.bus.unsubscribe(subscriber)
