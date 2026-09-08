"""Configuração central do Zee Assistant.

Todas as constantes ajustáveis vivem em ``config/config.json``.  O arquivo é
mesclado sobre um dicionário de padrões, portanto uma chave ausente nunca
derruba a aplicação — apenas volta ao padrão.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config" / "config.json"

log = logging.getLogger(__name__)

#: Padrões completos.  Serve como documentação viva do que é configurável.
DEFAULTS: Dict[str, Any] = {
    "app": {
        "host": "0.0.0.0",
        "port": 5000,
        "resources_file": "data/recursos.json",
        "auto_reload_resources": True,
        "error_auto_return_seconds": 5,
        "version": "1.0.0",
    },
    "ui": {
        "device_name": "Zee",
        "idle_hint": 'Diga "Oi, Zee"',
        "listening_text": "Oi! Estou ouvindo...",
        "waiting_text": "Aguardando usuário...",
        "processing_text": "Procurando conteúdo...",
        "not_found_text": "Não encontrei esse conteúdo.",
        "multiple_text": "Encontrei mais de uma opção.",
        "no_mic_text": "Microfone indisponível",
    },
    "voice": {
        "enabled": True,
        "model_path": "models/vosk/pt-br",
        "sample_rate": 16000,
        "block_size": 4000,
        "input_device": None,
        # Efeitos sonoros por momento do fluxo (ver app/audio.py: SoundBoard).
        "sounds": {
            "startup": "static/assets/audio/saudacao.mp3",
            "wakeword": "static/assets/audio/pode-falar.mp3",
            "found": "static/assets/audio/encontrei.mp3",
            "thinking": "static/assets/audio/vou-pensar.wav",
            "error": "static/assets/audio/erro.mp3",
        },
        "sound_tail_silence_seconds": 0.4,
        # Compatibilidade: usado apenas se "sounds.wakeword" não existir.
        "welcome_audio": "",
        "audio_players": [
            ["mpg123", "-q"],
            ["afplay"],
            ["mpv", "--really-quiet", "--no-video"],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
            ["cvlc", "--play-and-exit", "--intf", "dummy"],
        ],
        "audio_player_timeout_seconds": 15,
        "wakeword": {
            "phrases": [
                "oi zee", "oi zi", "oi zí", "oi zé", "oi ze", "oi zii",
                "oizee", "oizi", "ei zee", "ei zi", "olá zee", "oi zey",
                "oi zin", "oi zeca",
            ],
            "use_grammar": True,
            "grammar_phrases": [
                "oi", "oi zé", "oi zi", "oi zeca", "oi zen",
                "ei zé", "ei zi", "olá zé", "alô zi", "opa zé",
            ],
            "fuzzy_threshold": 82,
            "max_words": 4,
            "cooldown_seconds": 2.0,
            "phrase_threshold": 90,
            "structural": {
                "enabled": True,
                "greetings": ["oi", "ei", "ai", "olá", "alô", "opa", "oe", "hei"],
                "names": ["ze", "zi", "zey", "zin", "zeca"],
                "greeting_threshold": 80,
                "name_threshold": 74,
                "min_name_length": 2,
                "max_name_length": 4,
                "allow_name_only": False,
                "name_only_threshold": 90,
            },
        },
        "command": {
            "max_record_seconds": 8,
            "min_record_seconds": 0.8,
            "no_speech_timeout_seconds": 5.0,
            "silence_rms_threshold": 500,
            "silence_duration_seconds": 0.9,
            "min_speech_blocks": 2,
            "max_alternatives": 5,
            "pre_capture_flush_blocks": 1,
            "whisper": {
                "enabled": True,
                "binary": "tools/whisper.cpp/build/bin/whisper-cli",
                "model_path": "models/whisper/ggml-base-q5_1.bin",
                "language": "pt",
                "threads": 3,
                "timeout_seconds": 30,
                "persistent": True,
                "server_binary": "tools/whisper.cpp/build/bin/whisper-server",
                "server_host": "127.0.0.1",
                "server_port": 8178,
                "server_startup_timeout_seconds": 30,
            },
        },
    },
    "matching": {
        "confidence_threshold": 70,
        "ambiguity_margin": 8,
        "max_suggestions": 4,
        "title_weight": 0.8,
        "description_weight": 0.2,
        "type_bonus": 12,
        "type_penalty": 25,
        "synonyms": {"ia": "inteligencia artificial"},
        # Trechos que o reconhecedor escreve errado (o modelo PT-BR não tem
        # "podcast" no vocabulário e sempre transcreve "pode se"/"de pode").
        "phonetic_aliases": {
            "pode se": "podcast",
            "pode que se": "podcast",
            "pode ce": "podcast",
            "pode si": "podcast",
            "podi casti": "podcast",
            "pod caster": "podcast",
            "de pode": "de podcast",
            "o pode": "o podcast",
            "i a": "inteligencia artificial",
            "y a": "inteligencia artificial",
            # "áudios" no plural sai como "deus"/"ao deus" no modelo PT-BR.
            "lista de deus": "lista de audios",
            "lista de ao deus": "lista de audios",
            "lista de alvos": "lista de audios",
        },
    },
    "slm": {
        "enabled": True,
        "model_path": "models/slm/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
        "context_size": 512,
        "max_tokens": 48,
        "max_words": 24,
        "temperature": 0.2,
        "threads": 3,
    },
    "llm": {
        "enabled": False,
        "provider": "openai_compatible",
        "url": "",
        "model": "",
        "api_key_env": "LLM_API_KEY",
        "timeout_seconds": 10,
        "max_tokens": 48,
        "temperature": 0.2,
    },
    "tts": {
        "enabled": True,
        "model_path": "models/piper/pt_BR-faber-medium.onnx",
        "length_scale": 1.0,
        "volume": 1.0,
        "playback_timeout_seconds": 60,
    },
    "warmup": {
        "enabled": True,
        "delay_seconds": 5,
        "slm": True,
        "tts": True,
    },
    "network": {
        "manage_wifi": True,
        "interface": "wlan0",
        "ap_ssid_prefix": "Zee-Setup",
        "ap_password": "",
        "ap_connection_name": "zee-setup-ap",
        "ap_address": "10.42.0.1",
        "ap_prefix": 24,
        "captive_portal_port": 8080,
        "captive_portal_fallback_port": 8080,
        "wifi_recovery_timeout_seconds": 60,
        "boot_wait_seconds": 45,
        "check_interval_seconds": 10,
        "connect_timeout_seconds": 45,
        "connectivity_check_url": "http://connectivitycheck.gstatic.com/generate_204",
        "connectivity_check_timeout_seconds": 5,
        "use_sudo": True,
    },
    "logging": {
        "level": "INFO",
        "file": "logs/zee.log",
        "max_bytes": 1048576,
        "backup_count": 5,
        "console": True,
    },
}

#: Aliases "planos" aceitos por compatibilidade com configurações simples.
FLAT_ALIASES = {
    "wakeword": ("voice", "wakeword", "phrases"),
    "command_timeout_seconds": ("voice", "command", "max_record_seconds"),
    "wifi_recovery_timeout_seconds": ("network", "wifi_recovery_timeout_seconds"),
    "fuzzy_match_threshold": ("matching", "confidence_threshold"),
    "app_port": ("app", "port"),
    "resources_file": ("app", "resources_file"),
    "welcome_audio": ("voice", "sounds", "wakeword"),
    "vosk_model_path": ("voice", "model_path"),
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Mescla ``override`` sobre ``base`` recursivamente (sem mutar ``override``)."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _apply_flat_aliases(data: Dict[str, Any]) -> Dict[str, Any]:
    """Converte chaves planas legadas para o formato aninhado."""
    for flat_key, path in FLAT_ALIASES.items():
        if flat_key not in data:
            continue
        value = data.pop(flat_key)
        if flat_key == "wakeword" and isinstance(value, str):
            value = [value]
        cursor = data
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
            if not isinstance(cursor, dict):  # configuração inconsistente
                break
        else:
            cursor[path[-1]] = value
    return data


class Config:
    """Acesso thread-safe às configurações, com recarga sob demanda."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ load
    def load(self) -> Dict[str, Any]:
        raw: Dict[str, Any] = {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                raise ValueError("config.json deve conter um objeto JSON")
        except FileNotFoundError:
            log.warning("config.json não encontrado em %s — usando padrões", self.path)
        except (json.JSONDecodeError, ValueError) as exc:
            log.error("config.json inválido (%s) — usando padrões", exc)
            raw = {}

        raw = _apply_flat_aliases(dict(raw))
        with self._lock:
            self._data = _deep_merge(DEFAULTS, raw)
        return self._data

    # ------------------------------------------------------------------ read
    @property
    def data(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """``cfg.get("voice.wakeword.fuzzy_threshold", 80)``."""
        with self._lock:
            cursor: Any = self._data
            for part in dotted_key.split("."):
                if not isinstance(cursor, dict) or part not in cursor:
                    return default
                cursor = cursor[part]
            return copy.deepcopy(cursor)

    def override(self, dotted_key: str, value: Any) -> None:
        """Sobrescreve um valor em memória (usado pelos argumentos de CLI)."""
        parts = dotted_key.split(".")
        with self._lock:
            cursor = self._data
            for part in parts[:-1]:
                nxt = cursor.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cursor[part] = nxt
                cursor = nxt
            cursor[parts[-1]] = value

    def section(self, name: str) -> Dict[str, Any]:
        value = self.get(name, {})
        return value if isinstance(value, dict) else {}

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    # ------------------------------------------------------------------ util
    @staticmethod
    def resolve_path(value: Any) -> Optional[Path]:
        """Resolve caminhos relativos à raiz do projeto."""
        if not value:
            return None
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = BASE_DIR / path
        return path


_config: Optional[Config] = None
_config_lock = threading.Lock()


def get_config(path: Optional[Path] = None, reload: bool = False) -> Config:
    """Singleton de configuração."""
    global _config
    with _config_lock:
        if _config is None or path is not None:
            _config = Config(path)
        elif reload:
            _config.load()
        return _config
