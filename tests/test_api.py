"""API local: recursos, navegação, voz simulada e eventos."""

import json
import threading

import pytest

from app.config import Config
from app.server import create_app
from app.services import ZeeServices
from app.state import State


@pytest.fixture
def app(tmp_path, resources_file):
    """App completo, mas com voz e Wi-Fi desligados (sem hardware nos testes)."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "app": {"resources_file": str(resources_file), "port": 5999},
                "voice": {"enabled": False},
                "network": {"manage_wifi": False},
                "logging": {"console": False, "file": str(tmp_path / "zee.log")},
            }
        ),
        encoding="utf-8",
    )
    config = Config(config_path)
    services = ZeeServices(config)
    services.state.set_microphone(True, "mic-fake")
    services.state.set_model_loaded(True)
    application = create_app(services, config)
    application.config["TESTING"] = True
    application.zee_services = services
    return application


@pytest.fixture
def client(app):
    return app.test_client()


class TestRecursos:
    def test_lista_completa(self, client):
        payload = client.get("/api/resources").get_json()
        assert payload["total"] == 4
        assert payload["counts"]["video"] == 1

    def test_filtra_por_tipo(self, client):
        payload = client.get("/api/resources?tipo=livro").get_json()
        assert payload["total"] == 1
        assert payload["recursos"][0]["id"] == "rec_003"

    def test_tipo_invalido(self, client):
        assert client.get("/api/resources?tipo=planilha").status_code == 400

    def test_recurso_por_id(self, client):
        payload = client.get("/api/resources/rec_001").get_json()
        assert "/embed/" in payload["embed_url"]

    def test_recurso_inexistente(self, client):
        assert client.get("/api/resources/nao_existe").status_code == 404

    def test_path_traversal_bloqueado(self, client):
        response = client.get("/api/resources/..%2F..%2Fetc%2Fpasswd")
        assert response.status_code == 404


class TestNavegacao:
    def test_menu_desliga_wakeword(self, client):
        payload = client.post("/api/navigation", json={"view": "menu"}).get_json()
        assert payload["state"] == "MENU"
        assert payload["wakeword_enabled"] is False

    def test_home_liga_wakeword(self, client):
        client.post("/api/navigation", json={"view": "menu"})
        payload = client.post("/api/navigation/home").get_json()
        assert payload["state"] == "HOME_LISTENING"
        assert payload["wakeword_enabled"] is True

    def test_conteudo_valida_recurso(self, client):
        ok = client.post("/api/navigation", json={"view": "resource", "resource_id": "rec_002"})
        assert ok.get_json()["state"] == "RESOURCE_VIEW"
        erro = client.post("/api/navigation", json={"view": "resource", "resource_id": "xx"})
        assert erro.status_code == 404

    def test_tela_invalida(self, client):
        assert client.post("/api/navigation", json={"view": "root"}).status_code == 400


class TestVoz:
    def test_sem_fala_volta_diretamente_para_wakeword(self, app):
        app.zee_services.state.set_state(State.WAITING_USER)
        app.zee_services.voice._return_to_wakeword_after_silence()
        assert app.zee_services.state.state is State.HOME_LISTENING

    def test_simulacao_abre_recurso(self, app, client):
        payload = client.post(
            "/api/voice/simulate",
            json={"text": "quero assistir ao vídeo de introdução à inteligência artificial"},
        ).get_json()
        assert payload["result"]["status"] == "open"
        assert payload["result"]["resource"]["id"] == "rec_001"
        assert app.zee_services.state.state.value == "RESOURCE_VIEW"

    def test_simulacao_sem_resultado(self, app, client):
        payload = client.post("/api/voice/simulate", json={"text": "bolo de cenoura"}).get_json()
        assert payload["result"]["status"] == "not_found"
        assert app.zee_services.state.state.value == "ERROR"

    def test_pergunta_geral_vai_para_o_slm(self, app, client):
        spoken = []
        speech_done = threading.Event()

        class FakeSLM:
            def answer(self, text):
                assert text == "qual o valor de 10 + 10?"
                return "20"

        class FakeTTS:
            def speak(self, text):
                spoken.append(text)
                speech_done.set()
                return True

        app.zee_services.voice.slm = FakeSLM()
        app.zee_services.voice.tts = FakeTTS()
        app.zee_services.voice._return_home_after_answer = lambda: None
        payload = client.post(
            "/api/voice/simulate", json={"text": "qual o valor de 10 + 10?"}
        ).get_json()
        assert payload["result"]["status"] == "not_found"
        assert app.zee_services.state.state.value == "ANSWERING"
        assert app.zee_services.state.context["answer"] == "20"
        assert speech_done.wait(1.0) is True
        assert spoken == ["20"]

    def test_corrige_transcricao_demais_antes_do_slm(self, app, client):
        app.zee_services.matcher.phonetic_aliases["demais"] = "dez mais dez"
        recebido = []

        class FakeSLM:
            def answer(self, text):
                recebido.append(text)
                return "20"

        app.zee_services.voice.slm = FakeSLM()
        client.post("/api/voice/simulate", json={"text": "demais"})
        assert recebido == ["dez mais dez"]

    def test_recurso_nao_chama_o_slm(self, app, client):
        class FailingSLM:
            def answer(self, _text):
                raise AssertionError("recursos devem vencer o SLM")

        app.zee_services.voice.slm = FailingSLM()
        payload = client.post(
            "/api/voice/simulate",
            json={"text": "quero assistir ao vídeo de introdução à inteligência artificial"},
        ).get_json()
        assert payload["result"]["status"] == "open"

    def test_simulacao_abre_listagem(self, app, client):
        payload = client.post(
            "/api/voice/simulate", json={"text": "mostra a lista de podcasts"}
        ).get_json()
        assert payload["result"]["status"] == "open_list"
        assert payload["result"]["detected_type"] == "audio"
        assert app.zee_services.state.state.value == "RESOURCE_LIST"
        assert app.zee_services.state.context["return_to"] == "home"

    def test_listagem_por_toque_volta_ao_menu(self, app, client):
        response = client.post(
            "/api/navigation", json={"view": "list", "tipo": "video"}
        )
        assert response.status_code == 200
        assert app.zee_services.state.context["return_to"] == "menu"

    def test_retorno_principal_e_preservado_ao_voltar_do_conteudo(self, app, client):
        response = client.post(
            "/api/navigation",
            json={"view": "list", "tipo": "video", "return_to": "home"},
        )
        assert response.status_code == 200
        assert app.zee_services.state.context["return_to"] == "home"

    def test_simulacao_abre_menu(self, app, client):
        payload = client.post("/api/voice/simulate", json={"text": "abre o menu"}).get_json()
        assert payload["result"]["status"] == "open_menu"
        assert app.zee_services.state.state.value == "MENU"

    def test_texto_obrigatorio(self, client):
        assert client.post("/api/voice/simulate", json={}).status_code == 400

    def test_texto_muito_longo_rejeitado(self, client):
        assert client.post("/api/voice/simulate", json={"text": "a" * 400}).status_code == 400

    def test_match_nao_altera_estado(self, app, client):
        antes = app.zee_services.state.state.value
        payload = client.post("/api/voice/match", json={"text": "quero o podcast de ia"}).get_json()
        assert payload["resource"]["id"] == "rec_002"
        assert app.zee_services.state.state.value == antes


class TestSons:
    def test_lista_os_sons_no_status_da_voz(self, client):
        status = client.get("/api/voice/status").get_json()
        sons = status["sounds"]
        assert set(sons) == {"startup", "wakeword", "found", "error"}
        assert "tts" in status

    def test_som_invalido(self, client):
        response = client.post("/api/voice/sound", json={"name": "buzina"})
        assert response.status_code == 400
        assert "startup" in response.get_json()["sons"]

    def test_arquivo_ausente_responde_404(self, app, client):
        app.zee_services.sounds.configure({"found": "/caminho/que/nao/existe.mp3"})
        assert client.post("/api/voice/sound", json={"name": "found"}).status_code == 404

    def test_toca_som_existente(self, app, client, tmp_path):
        arquivo = tmp_path / "beep.mp3"
        arquivo.write_bytes(b"x")
        tocados = []
        app.zee_services.sounds.configure({"found": str(arquivo)})
        app.zee_services.sounds.player.play = lambda path, preempt=False: tocados.append(path)
        response = client.post("/api/voice/sound", json={"name": "found"})
        assert response.status_code == 200
        assert response.get_json()["ok"] is True

    def test_simulacao_de_wakeword_exige_microfone(self, app, client):
        app.zee_services.state.set_microphone(False, None)
        assert client.post("/api/voice/simulate", json={"wakeword": True}).status_code == 409


class TestStatusEEventos:
    def test_status(self, client):
        payload = client.get("/api/status").get_json()
        assert payload["resources"]["video"] == 1
        assert "wakeword_enabled" in payload
        assert "speech_recognizer" in payload
        assert "tts" in payload

    def test_healthz(self, client):
        assert client.get("/healthz").get_json()["ok"] is True

    def test_home_renderiza(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"MENU" in response.data
        assert b"PRINCIPAL" in response.data
        assert b'id="btn-list-back"' in response.data
        assert b"badge-recognizer" in response.data
        assert b"zee-circulo.mp4" in response.data
        assert b"<video" in response.data

    def test_portal_renderiza(self, client):
        response = client.get("/setup")
        assert response.status_code == 200
        assert "Configurar".encode() in response.data

    def test_eventos_enviam_estado_inicial(self, client):
        response = client.get("/api/events", buffered=False)
        assert response.headers["Content-Type"].startswith("text/event-stream")
        chunk = next(response.response)
        assert b"event: state" in chunk
        response.close()

    def test_endpoint_inexistente(self, client):
        assert client.get("/api/nao-existe").status_code == 404


class TestWifiApi:
    def test_status_wifi(self, client):
        payload = client.get("/api/wifi/status").get_json()
        assert "setup" in payload
        assert payload["setup"]["ap_ssid"].startswith("Zee-Setup")

    def test_connect_valida_ssid(self, client):
        assert client.post("/api/wifi/connect", json={"ssid": ""}).status_code == 400

    def test_connect_valida_senha_curta(self, client):
        response = client.post("/api/wifi/connect", json={"ssid": "Escola", "password": "123"})
        assert response.status_code == 400
        assert "8" in response.get_json()["message"]

    def test_setup_acao_invalida(self, client):
        assert client.post("/api/wifi/setup", json={"action": "explodir"}).status_code == 400
