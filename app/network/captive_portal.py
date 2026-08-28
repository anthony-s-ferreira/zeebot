"""Captive portal servido enquanto o Access Point de configuração está ativo.

Roda em um servidor HTTP próprio (porta 80 quando possível) para que o
smartphone abra a página automaticamente ao entrar na rede ``Zee-Setup-XXXX``.
Se a porta 80 não estiver disponível, cai para 8080 e tenta um redirecionamento
via iptables — e, em último caso, a tela do Zee mostra a URL com a porta.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from flask import Flask, jsonify, redirect, render_template, request

from ..config import BASE_DIR
from ..utils.proc import run, with_privileges

log = logging.getLogger(__name__)

#: URLs que os sistemas operacionais consultam para detectar captive portal.
DETECTION_PATHS = [
    "/generate_204",
    "/gen_204",
    "/mobile/status.php",
    "/hotspot-detect.html",
    "/library/test/success.html",
    "/success.txt",
    "/ncsi.txt",
    "/connecttest.txt",
    "/redirect",
    "/canonical.html",
    "/fwlink",
    "/kindle-wifi/wifistub.html",
]


class CaptivePortal:
    """Servidor HTTP leve com a página de configuração de Wi-Fi."""

    def __init__(self, config, supervisor) -> None:
        self.config = config
        self.supervisor = supervisor
        network = config.section("network")
        self.address = str(network.get("ap_address", "10.42.0.1"))
        self.port = int(network.get("captive_portal_port", 80))
        self.fallback_port = int(network.get("captive_portal_fallback_port", 8080))
        self.use_sudo = bool(network.get("use_sudo", True))

        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._redirect_installed = False
        self.active_port: Optional[int] = None

        self.app = self._build_app()

    # ------------------------------------------------------------------- app
    def _build_app(self) -> Flask:
        app = Flask(
            "zee-portal",
            template_folder=str(BASE_DIR / "templates"),
            static_folder=str(BASE_DIR / "static"),
        )
        app.config["JSON_AS_ASCII"] = False
        app.config["TEMPLATES_AUTO_RELOAD"] = False

        @app.get("/")
        def index():
            return render_template(
                "portal.html",
                device_name=self.config.get("ui.device_name", "Zee"),
                ap_address=self.address,
            )

        @app.get("/api/networks")
        def api_networks():
            return jsonify({"networks": self.supervisor.list_networks()})

        @app.get("/api/status")
        def api_status():
            return jsonify(self.supervisor.connection_status())

        @app.post("/api/connect")
        def api_connect():
            payload: Dict[str, Any] = request.get_json(silent=True) or request.form.to_dict() or {}
            ssid = payload.get("ssid")
            password = payload.get("password") or ""
            try:
                accepted, message = self.supervisor.request_connect(ssid, password)
            except ValueError as exc:  # validação de SSID/senha
                return jsonify({"ok": False, "message": str(exc)}), 400
            status = 202 if accepted else 409
            return jsonify({"ok": accepted, "message": message}), status

        def _portal_redirect():
            target = f"http://{self.address}{'' if self.active_port in (80, None) else f':{self.active_port}'}/"
            return redirect(target, code=302)

        for path in DETECTION_PATHS:
            app.add_url_rule(
                path,
                endpoint=f"detect_{path.strip('/').replace('/', '_').replace('.', '_')}",
                view_func=_portal_redirect,
                methods=["GET"],
            )

        @app.errorhandler(404)
        def not_found(_error):
            # Qualquer URL desconhecida leva o navegador para a configuração.
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "message": "não encontrado"}), 404
            return _portal_redirect()

        return app

    # ---------------------------------------------------------------- servidor
    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True

        from werkzeug.serving import make_server

        last_error: Optional[Exception] = None
        for port in (self.port, self.fallback_port):
            if port is None:
                continue
            try:
                self._server = make_server("0.0.0.0", port, self.app, threaded=True)
                self.active_port = port
                break
            except OSError as exc:
                last_error = exc
                log.warning("porta %s indisponível para o captive portal (%s)", port, exc)
        else:
            log.error("captive portal não pôde iniciar: %s", last_error)
            return False

        self._thread = threading.Thread(
            target=self._server.serve_forever, name="zee-portal", daemon=True
        )
        self._thread.start()
        log.info("captive portal ativo em http://%s:%s", self.address, self.active_port)

        if self.active_port != 80:
            self._install_redirect(self.active_port)
        return True

    def stop(self) -> None:
        self._remove_redirect()
        server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception as exc:  # pragma: no cover
                log.debug("erro ao parar captive portal: %s", exc)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self.active_port = None
        log.info("captive portal encerrado")

    # ------------------------------------------------------------- iptables
    def _install_redirect(self, port: int) -> None:
        """Redireciona 80 -> porta alternativa enquanto o portal estiver ativo."""
        result = run(
            with_privileges(
                [
                    "iptables", "-t", "nat", "-I", "PREROUTING", "1",
                    "-p", "tcp", "--dport", "80",
                    "-j", "REDIRECT", "--to-port", str(port),
                ],
                use_sudo=self.use_sudo,
            ),
            timeout=10.0,
        )
        self._redirect_installed = result.ok
        if result.ok:
            log.info("redirecionamento iptables 80 -> %s instalado", port)
        else:
            log.warning(
                "sem redirecionamento da porta 80 — acesse http://%s:%s manualmente",
                self.address, port,
            )

    def _remove_redirect(self) -> None:
        if not self._redirect_installed or not self.active_port:
            return
        run(
            with_privileges(
                [
                    "iptables", "-t", "nat", "-D", "PREROUTING",
                    "-p", "tcp", "--dport", "80",
                    "-j", "REDIRECT", "--to-port", str(self.active_port),
                ],
                use_sudo=self.use_sudo,
            ),
            timeout=10.0,
        )
        self._redirect_installed = False

    # --------------------------------------------------------------- utilidade
    @property
    def url(self) -> str:
        if self.active_port in (80, None):
            return f"http://{self.address}"
        return f"http://{self.address}:{self.active_port}"

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
