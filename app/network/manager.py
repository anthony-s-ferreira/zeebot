"""Supervisor de rede: decide entre "usar a aplicação" e "configurar o Wi-Fi".

Fluxo de boot:

1. Espera o NetworkManager conectar a um perfil salvo.
2. Se não conseguir dentro de ``wifi_recovery_timeout_seconds``, sobe o
   Access Point ``Zee-Setup-XXXX`` + captive portal e mostra o QR Code na tela.
3. Quando a conexão é concluída, derruba o AP e entra na Home.

O mesmo mecanismo funciona como recuperação: se o dispositivo for levado para
outro local e ficar sem rede, ele volta ao modo de configuração.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from ..state import State, StateMachine
from . import wifi
from .captive_portal import CaptivePortal

log = logging.getLogger(__name__)

SCAN_CACHE_SECONDS = 8.0


class NetworkSupervisor:
    """Coordena NetworkManager, Access Point e captive portal."""

    def __init__(self, config, state: StateMachine) -> None:
        self.config = config
        self.state = state

        network = config.section("network")
        self.manage_wifi = bool(network.get("manage_wifi", True))
        self.interface = str(network.get("interface", "wlan0"))
        self.ap_prefix = str(network.get("ap_ssid_prefix", "Zee-Setup"))
        self.ap_password = str(network.get("ap_password", "") or "")
        self.ap_connection = str(network.get("ap_connection_name", "zee-setup-ap"))
        self.ap_address = str(network.get("ap_address", "10.42.0.1"))
        self.ap_prefix_len = int(network.get("ap_prefix", 24))
        self.recovery_timeout = float(network.get("wifi_recovery_timeout_seconds", 60))
        self.boot_wait = float(network.get("boot_wait_seconds", 45))
        self.check_interval = float(network.get("check_interval_seconds", 10))
        self.connect_timeout = float(network.get("connect_timeout_seconds", 45))
        self.connectivity_url = str(network.get("connectivity_check_url", ""))
        self.connectivity_timeout = float(network.get("connectivity_check_timeout_seconds", 5))
        self.use_sudo = bool(network.get("use_sudo", True))

        self.ap_ssid = wifi.ap_ssid(self.ap_prefix)
        self.portal = CaptivePortal(config, self)

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._setup_mode = False
        self._connect_thread: Optional[threading.Thread] = None
        self._status: Dict[str, Any] = {
            "status": "idle",
            "message": "",
            "ssid": None,
            "ap_ssid": self.ap_ssid,
        }
        self._scan_cache: Tuple[float, List[Dict[str, Any]]] = (0.0, [])
        self._disconnected_since: Optional[float] = None

    # ------------------------------------------------------------------ ciclo
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="zee-network", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        if self._setup_mode:
            self.exit_setup_mode(go_home=False)

    def _run(self) -> None:
        if not self.manage_wifi:
            log.info("gerenciamento de Wi-Fi desativado — indo direto para a Home")
            self.state.set_state(State.HOME_LISTENING, reason="wifi não gerenciado")
            return

        if not wifi.nmcli_available():
            log.error("nmcli não encontrado: configuração de Wi-Fi indisponível")
            self.state.set_state(State.HOME_LISTENING, reason="sem NetworkManager")
            return

        if self._wait_for_connection(self.boot_wait):
            self._go_home()
        else:
            log.warning(
                "sem conexão Wi-Fi após %.0fs — entrando no modo de configuração", self.boot_wait
            )
            self.enter_setup_mode()

        while not self._stop.is_set():
            self._stop.wait(self.check_interval)
            if self._stop.is_set():
                break
            try:
                self._monitor()
            except Exception:  # pragma: no cover - thread não pode morrer
                log.exception("erro no supervisor de rede")

    def _wait_for_connection(self, timeout: float) -> bool:
        """Aguarda o NetworkManager subir um perfil salvo."""
        deadline = time.time() + max(0.0, timeout)
        attempted_reconnect = False
        while time.time() < deadline and not self._stop.is_set():
            if self._refresh_network_state():
                return True
            if not attempted_reconnect and not wifi.has_saved_wifi(self.ap_connection, self.use_sudo):
                log.info("nenhuma rede Wi-Fi salva neste dispositivo")
                return False
            if not attempted_reconnect:
                attempted_reconnect = True
                wifi.reconnect_saved(self.interface, self.use_sudo)
            self._stop.wait(2.0)
        return self._refresh_network_state()

    def _refresh_network_state(self) -> bool:
        info = wifi.active_wifi(self.interface, use_sudo=self.use_sudo)
        connected = (
            info.get("connection") != self.ap_connection
            and bool(info.get("ip"))
            and str(info.get("state", "")).startswith("100")
        )
        self.state.set_network(connected, info.get("ssid"), info.get("ip"))
        with self._lock:
            self._status["ssid"] = info.get("ssid")
        return connected

    def _monitor(self) -> None:
        connected = self._refresh_network_state()

        if self._setup_mode:
            with self._lock:
                connecting = self._status.get("status") == "connecting"
            if connected and not connecting:
                log.info("conexão detectada durante o setup — encerrando modo de configuração")
                self.exit_setup_mode()
            return

        if connected:
            self._disconnected_since = None
            return

        if self._disconnected_since is None:
            self._disconnected_since = time.time()
            log.warning("conexão Wi-Fi perdida — monitorando por %.0fs", self.recovery_timeout)
            return

        offline_for = time.time() - self._disconnected_since
        if offline_for < self.recovery_timeout:
            return

        # Só interrompe o usuário se ele estiver na Home ociosa.
        if self.state.state is not State.HOME_LISTENING:
            log.debug("recuperação de Wi-Fi adiada (estado atual: %s)", self.state.state.value)
            return

        log.warning("sem Wi-Fi há %.0fs — reentrando no modo de configuração", offline_for)
        self._disconnected_since = None
        self.enter_setup_mode()

    # ------------------------------------------------------------- setup mode
    def enter_setup_mode(self) -> bool:
        with self._lock:
            if self._setup_mode:
                return True
            self._setup_mode = True
            self._status.update({"status": "idle", "message": "", "ap_ssid": self.ap_ssid})

        ok, message = wifi.start_access_point(
            self.ap_ssid,
            self.ap_password,
            self.interface,
            self.ap_connection,
            self.ap_address,
            self.ap_prefix_len,
            self.use_sudo,
        )
        if not ok:
            log.error("não foi possível criar o Access Point: %s", message)
            with self._lock:
                self._status.update({"status": "ap_failed", "message": message})

        self.portal.start()
        self.state.set_state(State.WIFI_SETUP, self.setup_info(), reason="configuração de Wi-Fi")
        self.state.publish("wifi", self.setup_info())
        return ok

    def exit_setup_mode(self, go_home: bool = True) -> None:
        with self._lock:
            if not self._setup_mode:
                return
            self._setup_mode = False
        self.portal.stop()
        wifi.stop_access_point(self.ap_connection, self.use_sudo)
        self._refresh_network_state()
        if go_home:
            self._go_home()

    def _go_home(self) -> None:
        self.state.set_state(State.HOME_LISTENING, reason="rede pronta")
        self.state.publish("action", {"action": "go_home"})

    # ------------------------------------------------------------------ portal
    def list_networks(self) -> List[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            timestamp, cached = self._scan_cache
            if cached and (now - timestamp) < SCAN_CACHE_SECONDS:
                return cached
        networks = wifi.scan_networks(self.interface, rescan=True, use_sudo=self.use_sudo)
        networks = [n for n in networks if n["ssid"] != self.ap_ssid]
        with self._lock:
            self._scan_cache = (now, networks)
        return networks

    def connection_status(self) -> Dict[str, Any]:
        with self._lock:
            status = dict(self._status)
        status["setup_mode"] = self._setup_mode
        status["portal_url"] = self.portal.url
        return status

    def request_connect(self, ssid: Any, password: Any) -> Tuple[bool, str]:
        """Valida a entrada e dispara a conexão em segundo plano."""
        ssid = wifi.validate_ssid(ssid)
        password = wifi.validate_password(password)

        with self._lock:
            if self._status.get("status") == "connecting":
                return False, "Já existe uma tentativa de conexão em andamento."
            self._status.update(
                {"status": "connecting", "message": f"Conectando a {ssid}...", "ssid": ssid}
            )
            self._connect_thread = threading.Thread(
                target=self._connect_worker,
                args=(ssid, password),
                name="zee-wifi-connect",
                daemon=True,
            )
            thread = self._connect_thread
        # A senha nunca é registrada — apenas o SSID.
        log.info("solicitação de conexão recebida para %r", ssid)
        self.state.publish(
            "wifi", {**self.setup_info(), "status": "connecting", "ssid": ssid}
        )
        thread.start()
        return True, f"Conectando a {ssid}. Acompanhe pela tela do Zee."

    def _connect_worker(self, ssid: str, password: str) -> None:
        # O rádio é um só: para conectar à rede do usuário o AP precisa cair.
        wifi.stop_access_point(self.ap_connection, self.use_sudo)
        time.sleep(2.0)

        ok, message = wifi.connect(
            ssid, password, self.interface, self.connect_timeout, self.use_sudo
        )
        password = ""  # descarta o segredo o quanto antes

        if ok:
            self._refresh_network_state()
            online = wifi.check_internet(self.connectivity_url, self.connectivity_timeout)
            with self._lock:
                self._status.update(
                    {
                        "status": "connected",
                        "message": "Wi-Fi configurado com sucesso!",
                        "ssid": ssid,
                        "internet": online,
                    }
                )
            log.info("Wi-Fi configurado com sucesso (ssid=%r, internet=%s)", ssid, online)
            self.state.publish(
                "wifi",
                {
                    **self.setup_info(),
                    "status": "connected",
                    "ssid": ssid,
                    "internet": online,
                    "message": "Conectado!",
                },
            )
            time.sleep(4.0)
            self.exit_setup_mode()
            return

        with self._lock:
            self._status.update({"status": "failed", "message": message, "ssid": ssid})
        log.error("configuração de Wi-Fi falhou para %r: %s", ssid, message)

        # Regra da especificação: em caso de falha, o AP volta imediatamente.
        wifi.start_access_point(
            self.ap_ssid,
            self.ap_password,
            self.interface,
            self.ap_connection,
            self.ap_address,
            self.ap_prefix_len,
            self.use_sudo,
        )
        self.state.publish("wifi", {**self.setup_info(), "status": "failed", "message": message})

    # -------------------------------------------------------------- informação
    def setup_info(self) -> Dict[str, Any]:
        with self._lock:
            status = dict(self._status)
        return {
            "setup_mode": self._setup_mode,
            "ap_ssid": self.ap_ssid,
            "ap_secured": bool(self.ap_password),
            "portal_url": self.portal.url,
            "qr_payload": wifi.wifi_qr_payload(self.ap_ssid, self.ap_password),
            "status": status.get("status", "idle"),
            "message": status.get("message", ""),
            "ssid": status.get("ssid"),
        }

    @property
    def setup_mode(self) -> bool:
        with self._lock:
            return self._setup_mode

    def status(self) -> Dict[str, Any]:
        info = wifi.active_wifi(self.interface, use_sudo=self.use_sudo)
        return {
            "managed": self.manage_wifi,
            "interface": self.interface,
            "nmcli": wifi.nmcli_available(),
            "connected": bool(info.get("ip")) and info.get("connection") != self.ap_connection,
            "ssid": info.get("ssid"),
            "ip": info.get("ip"),
            "setup": self.setup_info(),
        }
