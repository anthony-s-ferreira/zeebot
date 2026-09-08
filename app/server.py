"""API HTTP local + SSE.

Comunicação backend -> frontend: **Server-Sent Events** em ``/api/events``.
É a opção de menor complexidade que atende ao requisito (o backend precisa
avisar a tela para navegar sozinha após um comando de voz) e reconecta
automaticamente no Chromium.
"""

from __future__ import annotations

import io
import json
import logging
import threading
from typing import Any, Dict, Iterator, Optional

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from .config import BASE_DIR, Config
from .resources import VALID_TYPES, normalize_type
from .services import ZeeServices
from .state import VIEW_TO_STATE, State

log = logging.getLogger(__name__)

SSE_KEEPALIVE_SECONDS = 15.0


def _sse(event: Dict[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False)
    return f"id: {event.get('seq', 0)}\nevent: {event.get('type', 'message')}\ndata: {payload}\n\n"


def create_app(services: ZeeServices, config: Optional[Config] = None) -> Flask:
    config = config or services.config
    app = Flask(
        "zee",
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
        static_url_path="/static",
    )
    app.config["JSON_AS_ASCII"] = False
    app.config["JSON_SORT_KEYS"] = False
    app.extensions["zee"] = services

    state = services.state
    library = services.library

    # ------------------------------------------------------------------ páginas
    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            ui=config.section("ui"),
            version=config.get("app.version", "1.0.0"),
        )

    @app.get("/setup")
    def setup_preview() -> str:
        """Mesma página do captive portal — útil para testar pelo desktop."""
        return render_template(
            "portal.html",
            device_name=config.get("ui.device_name", "Zee"),
            ap_address=config.get("network.ap_address", "10.42.0.1"),
        )

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "state": state.state.value})

    # -------------------------------------------------------------------- API
    @app.get("/api/status")
    def api_status():
        return jsonify(services.status())

    @app.get("/api/resources")
    def api_resources():
        tipo = request.args.get("tipo")
        if tipo:
            normalized = normalize_type(tipo)
            if normalized is None:
                return jsonify({"error": f"tipo inválido: {tipo}", "tipos": list(VALID_TYPES)}), 400
            items = library.by_type(normalized)
        else:
            items = library.all()
        return jsonify(
            {
                "recursos": [item.to_dict() for item in items],
                "total": len(items),
                "tipos": list(VALID_TYPES),
                "counts": library.counts(),
            }
        )

    @app.get("/api/resources/<resource_id>")
    def api_resource(resource_id: str):
        resource = library.get(resource_id)
        if resource is None:
            return jsonify({"error": "recurso não encontrado", "id": resource_id}), 404
        return jsonify(resource.to_dict())

    @app.post("/api/resources/reload")
    def api_resources_reload():
        library.load(force=True)
        state.publish("resources", {"counts": library.counts()})
        return jsonify({"ok": True, "counts": library.counts(), "error": library.last_error})

    # ------------------------------------------------------------- navegação
    @app.post("/api/navigation")
    def api_navigation():
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        view = str(payload.get("view", "")).lower().strip()
        if view not in VIEW_TO_STATE:
            return jsonify({"error": "tela inválida", "telas": sorted(VIEW_TO_STATE)}), 400

        context: Dict[str, Any] = {"source": "touch"}
        if view == "list":
            tipo = normalize_type(payload.get("tipo"))
            if payload.get("tipo") and tipo is None:
                return jsonify({"error": "tipo inválido"}), 400
            context["tipo"] = tipo
            context["mode"] = payload.get("mode") or "list"
            context["return_to"] = (
                "home" if payload.get("return_to") == "home" else "menu"
            )
        elif view == "resource":
            resource = library.get(payload.get("resource_id"))
            if resource is None:
                return jsonify({"error": "recurso não encontrado"}), 404
            context["resource_id"] = resource.id
            context["tipo"] = resource.tipo
            context["return_to"] = (
                "home" if payload.get("return_to") == "home" else "menu"
            )

        new_state = state.set_view(view, context)
        return jsonify({"ok": True, "state": new_state.value, "wakeword_enabled": state.wakeword_enabled})

    @app.post("/api/navigation/home")
    def api_navigation_home():
        new_state = services.go_home()
        return jsonify({"ok": True, "state": new_state.value, "wakeword_enabled": state.wakeword_enabled})

    # ------------------------------------------------------------------- voz
    @app.get("/api/voice/status")
    def api_voice_status():
        return jsonify(services.voice.status())

    @app.post("/api/voice/simulate")
    def api_voice_simulate():
        """Dispara o ciclo de voz sem microfone (procedimento de teste).

        Com ``{"wakeword": true}`` executa o ciclo completo — toca o
        "pode falar" e grava do microfone, como se você tivesse dito "Oi, Zee".
        """
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        if payload.get("wakeword") and not payload.get("text"):
            if not state.snapshot()["microphone"]["available"]:
                return jsonify({"error": "microfone indisponível"}), 409
            threading.Thread(
                target=services.voice.run_interaction, daemon=True, name="zee-simulacao"
            ).start()
            return jsonify({"ok": True, "mode": "wakeword"}), 202

        text = str(payload.get("text", "")).strip()
        if not text:
            return jsonify({"error": "informe o campo 'text'"}), 400
        if len(text) > 300:
            return jsonify({"error": "comando muito longo"}), 400
        result = services.voice.simulate_command(text)
        return jsonify({"ok": True, "result": result.to_dict(services.matcher.max_suggestions)})

    @app.post("/api/voice/sound")
    def api_voice_sound():
        """Toca um efeito sonoro — usado para testar o alto-falante."""
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        name = str(payload.get("name", "")).strip().lower()
        if name not in services.sounds.NAMES:
            return jsonify({"error": "som inválido", "sons": list(services.sounds.NAMES)}), 400
        if not services.sounds.exists(name):
            return jsonify({"ok": False, "error": f"arquivo do som '{name}' não encontrado"}), 404
        services.sounds.play(name, blocking=False)
        return jsonify({"ok": True, "name": name, "path": str(services.sounds.path(name))})

    @app.post("/api/voice/match")
    def api_voice_match():
        """Só a busca, sem mexer no estado — ideal para calibrar o threshold."""
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        text = str(payload.get("text", "")).strip()
        if not text:
            return jsonify({"error": "informe o campo 'text'"}), 400
        result = services.matcher.search(text)
        return jsonify(result.to_dict(10))

    # ------------------------------------------------------------------ wi-fi
    @app.get("/api/wifi/status")
    def api_wifi_status():
        return jsonify(services.network.status())

    @app.get("/api/wifi/networks")
    def api_wifi_networks():
        return jsonify({"networks": services.network.list_networks()})

    @app.post("/api/wifi/connect")
    def api_wifi_connect():
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        try:
            accepted, message = services.network.request_connect(
                payload.get("ssid"), payload.get("password") or ""
            )
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        return jsonify({"ok": accepted, "message": message}), (202 if accepted else 409)

    @app.post("/api/wifi/setup")
    def api_wifi_setup():
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        action = str(payload.get("action", "")).lower()
        if action == "start":
            ok = services.network.start_setup_mode()
            setup = services.network.setup_info()
            return jsonify({"ok": ok, "setup": setup}), 202
        if action == "stop":
            services.network.exit_setup_mode()
            return jsonify({"ok": True, "setup": services.network.setup_info()})
        return jsonify({"error": "ação inválida (use start ou stop)"}), 400

    @app.get("/api/wifi/qrcode.svg")
    def api_wifi_qrcode():
        info = services.network.setup_info()
        payload = request.args.get("payload") or info["qr_payload"]
        svg = _render_qrcode(payload)
        if svg is None:
            return jsonify({"error": "biblioteca qrcode indisponível"}), 503
        return Response(
            svg,
            mimetype="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )

    # ----------------------------------------------------------------- eventos
    @app.get("/api/events")
    def api_events() -> Response:
        def stream() -> Iterator[str]:
            subscriber = services.bus.subscribe()
            try:
                yield _sse({"seq": 0, "type": "state", "data": state.snapshot()})
                yield _sse({"seq": 0, "type": "wifi", "data": services.network.setup_info()})
                while True:
                    event = subscriber.get(timeout=SSE_KEEPALIVE_SECONDS)
                    if event is None:
                        yield ": keepalive\n\n"
                    else:
                        yield _sse(event)
            except GeneratorExit:  # cliente fechou a aba/recarregou
                raise
            finally:
                services.bus.unsubscribe(subscriber)

        return Response(
            stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------ erros
    @app.after_request
    def no_store(response: Response) -> Response:
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(404)
    def handle_404(_error):
        if request.path.startswith(("/api/", "/static/")):
            return jsonify({"error": "não encontrado", "path": request.path}), 404
        # Qualquer outra rota devolve a aplicação (o roteamento é no frontend).
        return render_template(
            "index.html", ui=config.section("ui"), version=config.get("app.version", "1.0.0")
        ), 200

    @app.errorhandler(Exception)
    def handle_error(error: Exception):
        if isinstance(error, HTTPException):
            return error  # 405, 400 etc. mantêm a resposta padrão do Werkzeug
        log.exception("erro não tratado em %s", request.path)
        if request.path.startswith("/api/"):
            return jsonify({"error": "erro interno", "detail": str(error)}), 500
        return "Erro interno no Zee Assistant", 500

    return app


def _render_qrcode(payload: str) -> Optional[str]:
    """Gera o QR Code em SVG (sem depender do Pillow)."""
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        log.error("pacote qrcode não instalado — QR Code indisponível")
        return None
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
        buffer = io.BytesIO()
        image.save(buffer)
        return buffer.getvalue().decode("utf-8")
    except Exception as exc:  # pragma: no cover
        log.error("falha ao gerar QR Code: %s", exc)
        return None
