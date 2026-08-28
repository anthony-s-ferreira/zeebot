"""Camada de rede: parsing do nmcli, validação e QR Code."""

import pytest

from app.network import wifi


class TestParsingTerse:
    def test_divide_campos(self):
        assert wifi.parse_terse_line("*:MinhaCasa:78:WPA2") == ["*", "MinhaCasa", "78", "WPA2"]

    def test_respeita_dois_pontos_escapados(self):
        campos = wifi.parse_terse_line("*:Rede\\: Escola:60:WPA2")
        assert campos[1] == "Rede: Escola"

    def test_campo_vazio(self):
        assert wifi.parse_terse_line("::") == ["", "", ""]


class TestValidacao:
    @pytest.mark.parametrize("ssid", ["MinhaCasa", "Escola WiFi", "Rede-Visitantes", "café_2G"])
    def test_ssid_valido(self, ssid):
        assert wifi.validate_ssid(ssid) == ssid

    @pytest.mark.parametrize("ssid", ["", "   ", None, "-rede", "x" * 40, "rede\ncom quebra"])
    def test_ssid_invalido(self, ssid):
        with pytest.raises(ValueError):
            wifi.validate_ssid(ssid)

    def test_senha_vazia_permitida(self):
        assert wifi.validate_password("") == ""
        assert wifi.validate_password(None) == ""

    @pytest.mark.parametrize("senha", ["123", "x" * 70])
    def test_senha_invalida(self, senha):
        with pytest.raises(ValueError):
            wifi.validate_password(senha)

    def test_senha_valida(self):
        assert wifi.validate_password("segredo123") == "segredo123"


class TestQrCode:
    def test_rede_aberta(self):
        payload = wifi.wifi_qr_payload("Zee-Setup-AB12")
        assert payload == "WIFI:T:nopass;S:Zee-Setup-AB12;;"

    def test_rede_com_senha(self):
        payload = wifi.wifi_qr_payload("Zee-Setup-AB12", "abelha123")
        assert "T:WPA" in payload and "P:abelha123" in payload

    def test_escapa_caracteres_especiais(self):
        payload = wifi.wifi_qr_payload("Rede;Teste:1")
        assert "\;" in payload and "\\:" in payload


class TestIdentificacao:
    def test_sufixo_do_dispositivo(self):
        suffix = wifi.device_suffix()
        assert len(suffix) == 4 and suffix.isalnum()

    def test_ssid_do_access_point(self):
        ssid = wifi.ap_ssid("Zee-Setup")
        assert ssid.startswith("Zee-Setup-") and len(ssid) <= 32


class TestSegurancaDeLog:
    def test_senha_e_mascarada_no_log(self):
        from app.utils.proc import sanitize_for_log

        args = ["nmcli", "device", "wifi", "connect", "Escola", "password", "segredo123"]
        seguro = sanitize_for_log(args, "segredo123")
        assert "segredo123" not in " ".join(seguro)
        assert seguro[-1] == "***"

    def test_filtro_de_log_redige_senha(self):
        import logging

        from app.logging_setup import RedactSecretsFilter

        record = logging.LogRecord(
            "t", logging.INFO, __file__, 1, "conectando com password=minhasenha", (), None
        )
        RedactSecretsFilter().filter(record)
        assert "minhasenha" not in record.getMessage()
