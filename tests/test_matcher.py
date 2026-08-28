"""Busca fuzzy, classificação de intenção e níveis de confiança."""

import pytest

from app.voice.matcher import (
    STATUS_MULTIPLE,
    STATUS_NOT_FOUND,
    STATUS_OPEN,
    STATUS_OPEN_LIST,
)


class TestComandosDaEspecificacao:
    @pytest.mark.parametrize(
        "frase,esperado",
        [
            ("Quero assistir ao vídeo de introdução à inteligência artificial", "rec_001"),
            ("Quero ouvir o podcast de inteligência artificial", "rec_002"),
            ("Abra o livro fundamentos de inteligência artificial", "rec_003"),
            ("Quero jogar o jogo do ABC", "rec_004"),
        ],
    )
    def test_abre_recurso_correto(self, matcher, frase, esperado):
        result = matcher.search(frase)
        assert result.status == STATUS_OPEN
        assert result.best.resource.id == esperado
        assert result.confidence >= matcher.threshold

    @pytest.mark.parametrize(
        "frase,esperado",
        [
            ("abra introdução inteligência artificial", "rec_001"),
            ("quero o podcast de IA", "rec_002"),
            ("abra fundamentos de inteligência artificial", "rec_003"),
            ("quero jogar abc", "rec_004"),
        ],
    )
    def test_frases_curtas(self, matcher, frase, esperado):
        result = matcher.search(frase)
        assert result.best is not None
        assert result.best.resource.id == esperado, result.to_dict()


class TestApelidos:
    """O modelo de voz não transcreve siglas ("ABC" vira "se") — daí os apelidos."""

    @pytest.mark.parametrize(
        "frase",
        [
            "quero jogar o jogo do alfabeto",
            "quero jogar o jogo das letras",
            "quero brincar com o abecedário",
        ],
    )
    def test_encontra_pelo_apelido(self, matcher, frase):
        result = matcher.search(frase)
        assert result.status == STATUS_OPEN
        assert result.best.resource.id == "rec_004"

    def test_titulo_continua_funcionando(self, matcher):
        assert matcher.search("quero jogar o jogo do abc").best.resource.id == "rec_004"

    def test_apelido_nao_vaza_para_outro_recurso(self, matcher):
        result = matcher.search("quero assistir o vídeo do alfabeto")
        assert result.status != STATUS_OPEN or result.best.resource.id == "rec_004"


class TestIntencao:
    def test_detecta_audio(self, matcher):
        result = matcher.search("quero ouvir podcast inteligência artificial")
        assert result.detected_type == "audio"
        assert result.best.resource.tipo == "audio"

    def test_detecta_video(self, matcher):
        result = matcher.search("quero assistir introdução inteligência artificial")
        assert result.detected_type == "video"
        assert result.best.resource.id == "rec_001"

    def test_tipo_desempata_titulos_parecidos(self, matcher):
        """Três títulos citam 'Inteligência Artificial' — o tipo decide."""
        video = matcher.search("quero ver inteligência artificial")
        audio = matcher.search("quero escutar inteligência artificial")
        livro = matcher.search("quero ler inteligência artificial")
        assert video.best.resource.tipo == "video"
        assert audio.best.resource.tipo == "audio"
        assert livro.best.resource.tipo == "livro"

    def test_normalizacao_de_acentos_no_comando(self, matcher):
        com = matcher.search("quero assistir introdução à inteligência artificial")
        sem = matcher.search("quero assistir introducao a inteligencia artificial")
        assert com.best.resource.id == sem.best.resource.id == "rec_001"


class TestConfianca:
    def test_nao_encontrado(self, matcher):
        result = matcher.search("quero uma receita de bolo de cenoura")
        assert result.status == STATUS_NOT_FOUND

    def test_score_entre_0_e_100(self, matcher):
        result = matcher.search("introdução inteligência artificial")
        for candidate in result.candidates:
            assert 0 <= candidate.score <= 100

    def test_apenas_o_tipo_abre_a_listagem(self, matcher):
        result = matcher.search("quero ver vídeos")
        assert result.status == STATUS_OPEN_LIST
        assert result.detected_type == "video"

    def test_ambiguidade_gera_multiplas_opcoes(self, matcher):
        """Com margem alta, títulos próximos viram lista de opções."""
        matcher.configure(
            {
                "confidence_threshold": 40,
                "ambiguity_margin": 60,
                "max_suggestions": 4,
                "type_bonus": 0,
                "type_penalty": 0,
                "synonyms": {"ia": "inteligencia artificial"},
            }
        )
        result = matcher.search("inteligência artificial")
        assert result.status == STATUS_MULTIPLE
        assert 2 <= len(result.candidates) <= 4

    def test_threshold_configuravel(self, matcher):
        matcher.configure({"confidence_threshold": 99.9, "ambiguity_margin": 0})
        result = matcher.search("bolo de cenoura")
        assert result.status == STATUS_NOT_FOUND

    def test_catalogo_vazio_nao_quebra(self, matcher):
        result = matcher.search("qualquer coisa", resources=[])
        assert result.status == STATUS_NOT_FOUND
        assert result.best is None

    def test_serializacao_para_o_frontend(self, matcher):
        payload = matcher.search("quero ver o vídeo de introdução à ia").to_dict()
        assert payload["status"] == STATUS_OPEN
        assert payload["resource"]["id"] == "rec_001"
        assert payload["candidates"][0]["score"] >= payload["candidates"][-1]["score"]
