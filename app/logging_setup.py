"""Configuração de logging com rotação e redação de segredos.

Regra do projeto: **senha de Wi-Fi nunca vai para o log**.  Além de nunca
passarmos a senha para o logger, um filtro de redação atua como rede de
segurança para qualquer mensagem que escape dessa disciplina.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

SECRET_PATTERNS = [
    re.compile(r"(?i)(password|senha|psk|passwd|pwd|key-mgmt-psk)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(--password|password)\s+\S+"),
    re.compile(r"(?i)(wifi-sec\.psk)\s+\S+"),
]

REDACTED = r"\1=***"


class RedactSecretsFilter(logging.Filter):
    """Substitui possíveis senhas por ``***`` antes da escrita."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - formatação defeituosa
            return True
        redacted = message
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub(REDACTED, redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def redact(value: Optional[str]) -> str:
    """Helper para mostrar que existe um segredo sem revelá-lo."""
    if not value:
        return "<vazio>"
    return f"<{len(value)} caracteres ocultos>"


def setup_logging(config: Dict[str, Any], base_dir: Path) -> logging.Logger:
    """Instala handlers de arquivo (rotativo) e console no logger raiz."""
    level_name = str(config.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    log_file = config.get("file", "logs/zee.log")
    path = Path(log_file)
    if not path.is_absolute():
        path = base_dir / path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - filesystem read-only
        print(f"[zee] não foi possível criar {path.parent}: {exc}", file=sys.stderr)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redactor = RedactSecretsFilter()

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=int(config.get("max_bytes", 1_048_576)),
            backupCount=int(config.get("backup_count", 5)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        root.addHandler(file_handler)
    except OSError as exc:  # pragma: no cover
        print(f"[zee] logging em arquivo desativado: {exc}", file=sys.stderr)

    if config.get("console", True):
        console = logging.StreamHandler(stream=sys.stdout)
        console.setFormatter(formatter)
        console.addFilter(redactor)
        root.addHandler(console)

    # Bibliotecas verbosas demais para um Raspberry Pi.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return logging.getLogger("zee")
