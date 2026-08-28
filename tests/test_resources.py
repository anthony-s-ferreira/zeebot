"""Parser do JSON de recursos e conversão de URLs."""

import json

import pytest

from app.resources import (
    VALID_TYPES,
    ResourceLibrary,
    normalize_type,
    parse_resources,
    to_embed_url,
)


class TestParser:
    def test_carrega_todos_os_recursos(self, library):
        assert len(library.all()) == 4

    def test_tipos_validos(self, library):
        for resource in library.all():
            assert resource.tipo in VALID_TYPES

    def test_filtra_por_tipo(self, library):
        assert [r.id for r in library.by_type("video")] == ["rec_001"]
        assert [r.id for r in library.by_type("audio")] == ["rec_002"]
        assert [r.id for r in library.by_type("livro")] == ["rec_003"]
        assert [r.id for r in library.by_type("jogo")] == ["rec_004"]

    def test_busca_por_id(self, library):
        assert library.get("rec_003").titulo == "Fundamentos de Inteligência Artificial"
        assert library.get("inexistente") is None
        assert library.get("") is None

    def test_contagem_por_tipo(self, library):
        assert library.counts() == {"video": 1, "audio": 1, "livro": 1, "jogo": 1}

    def test_aliases_carregados(self, library):
        jogo = library.get("rec_004")
        assert "jogo do alfabeto" in jogo.aliases
        assert jogo.to_dict()["aliases"] == jogo.aliases

    def test_aliases_opcionais(self, library):
        assert library.get("rec_001").aliases == []

    def test_aceita_chave_sinonimos_e_string(self):
        recursos = parse_resources(
            [
                {"id": "a", "tipo": "video", "titulo": "T", "sinonimos": ["apelido"]},
                {"id": "b", "tipo": "video", "titulo": "T2", "aliases": "único"},
            ]
        )
        assert recursos[0].aliases == ["apelido"]
        assert recursos[1].aliases == ["único"]

    def test_aceita_lista_pura(self):
        recursos = parse_resources([{"id": "x", "tipo": "video", "titulo": "T"}])
        assert len(recursos) == 1

    def test_ignora_item_invalido_sem_quebrar(self):
        payload = {
            "recursos": [
                {"id": "ok", "tipo": "video", "titulo": "Bom"},
                {"id": "ruim", "tipo": "planilha", "titulo": "Tipo inválido"},
                {"id": "sem_titulo", "tipo": "video"},
                "isso não é um objeto",
            ]
        }
        recursos = parse_resources(payload)
        assert [r.id for r in recursos] == ["ok"]

    def test_normaliza_tipo_com_acento(self):
        assert normalize_type("Vídeo") == "video"
        assert normalize_type("ÁUDIOS") == "audio"
        assert normalize_type("planilha") is None

    def test_recarrega_quando_arquivo_muda(self, resources_file, library):
        assert len(library.all()) == 4
        payload = json.loads(resources_file.read_text(encoding="utf-8"))
        payload["recursos"].append(
            {"id": "rec_005", "tipo": "video", "titulo": "Novo vídeo", "descricao": ""}
        )
        # mtime precisa mudar de forma perceptível
        resources_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import os, time

        future = time.time() + 5
        os.utime(resources_file, (future, future))
        assert len(library.all()) == 5

    def test_json_invalido_mantem_catalogo(self, resources_file, library):
        import os, time

        resources_file.write_text("{ isso não é json", encoding="utf-8")
        future = time.time() + 5
        os.utime(resources_file, (future, future))
        assert len(library.all()) == 4  # catálogo anterior preservado

    def test_arquivo_ausente_nao_quebra(self, tmp_path):
        library = ResourceLibrary(tmp_path / "nao_existe.json")
        assert library.all() == []
        assert library.last_error is not None


class TestEmbedUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=30",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        ],
    )
    def test_converte_youtube(self, url):
        assert to_embed_url(url).startswith("https://www.youtube.com/embed/dQw4w9WgXcQ")

    def test_mantem_embed_existente(self):
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        assert to_embed_url(url) == url

    def test_mantem_url_nao_youtube(self):
        url = "https://exemplo.com/video.mp4"
        assert to_embed_url(url) == url

    def test_url_vazia(self):
        assert to_embed_url("") == ""

    def test_embed_no_dict_do_recurso(self, library):
        video = library.get("rec_001").to_dict()
        assert "/embed/" in video["embed_url"]
        assert video["thumbnail"] is None  # propriedade opcional
