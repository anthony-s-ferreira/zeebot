"""Fixtures compartilhadas dos testes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config import Config  # noqa: E402
from app.resources import ResourceLibrary  # noqa: E402
from app.voice.matcher import ResourceMatcher  # noqa: E402

SAMPLE_RESOURCES = {
    "recursos": [
        {
            "id": "rec_001",
            "tipo": "video",
            "titulo": "Introdução à Inteligência Artificial",
            "descricao": "Vídeo apresentando os principais conceitos de IA.",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
        {
            "id": "rec_002",
            "tipo": "audio",
            "titulo": "Podcast de Inteligência Artificial",
            "descricao": "Discussão sobre aplicações práticas de IA.",
            "url": "https://conteudos.exemplo.com/audio/inteligencia-artificial.mp3",
        },
        {
            "id": "rec_003",
            "tipo": "livro",
            "titulo": "Fundamentos de Inteligência Artificial",
            "descricao": "Livro digital para aprofundamento do conteúdo.",
            "url": "https://conteudos.exemplo.com/livros/fundamentos-ia.pdf",
        },
        {
            "id": "rec_004",
            "tipo": "jogo",
            "titulo": "Jogo do ABC",
            "descricao": "Jogo educacional para aprendizagem do alfabeto.",
            "url": "https://conteudos.exemplo.com/jogos/abc.html",
            "aliases": ["jogo do alfabeto", "jogo das letras", "abecedário"],
        },
    ]
}


@pytest.fixture
def resources_file(tmp_path: Path) -> Path:
    path = tmp_path / "recursos.json"
    path.write_text(json.dumps(SAMPLE_RESOURCES, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def library(resources_file: Path) -> ResourceLibrary:
    return ResourceLibrary(resources_file)


@pytest.fixture
def config() -> Config:
    return Config(BASE_DIR / "config" / "config.json")


@pytest.fixture
def matcher(library: ResourceLibrary, config: Config) -> ResourceMatcher:
    return ResourceMatcher(library, config.section("matching"))
