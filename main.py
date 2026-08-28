#!/usr/bin/env python3
"""Ponto de entrada do Zee Assistant.

Um único processo com três threads de longa duração:

* servidor HTTP (Flask/Werkzeug, com SSE);
* motor de voz (Vosk);
* supervisor de rede (NetworkManager + captive portal).

Um processo só economiza memória no Raspberry Pi e elimina IPC entre voz e
interface — o estado vive em memória compartilhada, protegido por locks.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config import Config  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402
from app.server import create_app  # noqa: E402
from app.services import ZeeServices  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Zee Assistant")
    parser.add_argument("--config", type=Path, default=None, help="caminho do config.json")
    parser.add_argument("--host", default=None, help="endereço de escuta")
    parser.add_argument("--port", type=int, default=None, help="porta HTTP")
    parser.add_argument("--no-voice", action="store_true", help="desativa o motor de voz")
    parser.add_argument("--no-wifi", action="store_true", help="não gerencia Wi-Fi/Access Point")
    parser.add_argument("--debug", action="store_true", help="log em nível DEBUG")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    config = Config(args.config)

    logging_cfg = config.section("logging")
    if args.debug:
        logging_cfg["level"] = "DEBUG"
    log = setup_logging(logging_cfg, BASE_DIR)

    if args.no_voice:
        config.override("voice.enabled", False)
    if args.no_wifi:
        config.override("network.manage_wifi", False)

    host = args.host or config.get("app.host", "0.0.0.0")
    port = int(args.port or config.get("app.port", 5000))

    log.info("=" * 62)
    log.info("Zee Assistant %s iniciando", config.get("app.version", "1.0.0"))
    log.info("diretório base: %s", BASE_DIR)
    log.info("interface web: http://127.0.0.1:%s", port)
    log.info("=" * 62)

    services = ZeeServices(config)
    app = create_app(services, config)

    from werkzeug.serving import make_server

    try:
        server = make_server(host, port, app, threaded=True)
    except OSError as exc:
        log.error("não foi possível abrir a porta %s: %s", port, exc)
        return 1

    shutdown = threading.Event()

    def handle_signal(signum, _frame):
        log.info("sinal %s recebido — encerrando", signal.Signals(signum).name)
        shutdown.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_signal)
        except ValueError:  # pragma: no cover - fora da thread principal
            pass

    services.start()
    log.info("servidor pronto em http://%s:%s", host, port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        log.info("interrompido pelo teclado")
    finally:
        services.stop()
        try:
            server.server_close()
        except Exception:  # pragma: no cover
            pass
        logging.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
