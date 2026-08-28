"""Normalização de texto: acentos, maiúsculas, pontuação e tipos."""

import pytest

from app.utils.text import (
    apply_phrase_aliases,
    apply_synonyms,
    clean_query,
    detect_list_intent,
    detect_type,
    detect_type_detailed,
    normalize,
    remove_stopwords,
    strip_accents,
    tokenize,
)


class TestNormalizacao:
    def test_remove_acentos(self):
        assert strip_accents("Introdução à Inteligência") == "Introducao a Inteligencia"

    def test_minusculas_e_pontuacao(self):
        assert normalize("Olá, Zee! Tudo bem?") == "ola zee tudo bem"

    def test_espacos_normalizados(self):
        assert normalize("  muitos    espaços   ") == "muitos espacos"

    def test_texto_vazio_nao_quebra(self):
        assert normalize("") == ""
        assert normalize(None) == ""
        assert tokenize("") == []

    def test_variacoes_convergem(self):
        formas = [
            "Introdução à Inteligência Artificial",
            "INTRODUCAO A INTELIGENCIA ARTIFICIAL",
            "introdução, à inteligência artificial!",
        ]
        assert len({normalize(f) for f in formas}) == 1


class TestStopwords:
    def test_remove_palavras_irrelevantes(self):
        assert remove_stopwords("quero o video de inteligencia") == "video inteligencia"

    def test_nunca_devolve_vazio(self):
        assert remove_stopwords("quero o de a") != ""


class TestSinonimos:
    def test_expande_sigla(self):
        expandido = apply_synonyms("podcast de ia", {"ia": "inteligencia artificial"})
        assert expandido == "podcast de inteligencia artificial"


class TestDeteccaoDeTipo:
    def test_video(self):
        tipo, _ = detect_type("quero assistir ao vídeo de introdução")
        assert tipo == "video"

    def test_audio_por_podcast(self):
        tipo, _ = detect_type("quero ouvir o podcast de inteligência artificial")
        assert tipo == "audio"

    def test_livro_por_ler(self):
        tipo, _ = detect_type("quero ler o livro de fundamentos")
        assert tipo == "livro"

    def test_jogo_por_jogar(self):
        tipo, _ = detect_type("quero jogar o jogo do abc")
        assert tipo == "jogo"

    def test_pdf_indica_livro(self):
        tipo, _ = detect_type("abra o pdf de fundamentos")
        assert tipo == "livro"

    def test_sem_palavra_chave(self):
        tipo, palavras = detect_type("abra introdução inteligência artificial")
        assert tipo is None and palavras == []


class TestCleanQuery:
    def test_remove_tipo_e_stopwords(self):
        limpo = clean_query(
            "quero assistir ao vídeo de introdução à inteligência artificial",
            {"ia": "inteligencia artificial"},
        )
        assert "video" not in limpo
        assert "introducao" in limpo and "inteligencia" in limpo and "artificial" in limpo


class TestTiposFortesEFracos:
    """Substantivos vencem verbos: "mostra a lista de podcasts" é áudio."""

    def test_substantivo_vence_verbo(self):
        tipo, _ = detect_type("mostra a lista de podcasts")
        assert tipo == "audio"

    def test_verbo_vale_quando_nao_ha_substantivo(self):
        tipo, _ = detect_type("quero escutar inteligência artificial")
        assert tipo == "audio"

    def test_forca_reportada(self):
        assert detect_type_detailed("quero o podcast")[2] == "strong"
        assert detect_type_detailed("quero ouvir isso")[2] == "weak"
        assert detect_type_detailed("bom dia")[2] is None

    def test_novos_verbos_de_audio(self):
        assert detect_type("toca o podcast")[0] == "audio"

    def test_livro_por_estudar(self):
        assert detect_type("quero estudar o material")[0] == "livro"


class TestIntencaoDeListagem:
    @pytest.mark.parametrize(
        "frase",
        [
            "lista de vídeos",
            "mostra a lista de podcasts",
            "quais jogos existem",
            "mostra todos os livros",
            "quero ver todas as músicas",
            "abre o menu",
            "mostra tudo",
        ],
    )
    def test_detecta(self, frase):
        assert detect_list_intent(frase) is True

    @pytest.mark.parametrize(
        "frase",
        [
            "quero assistir ao vídeo de introdução",
            "abra o livro fundamentos",
            "quero jogar o jogo do alfabeto",
        ],
    )
    def test_nao_detecta_em_pedido_especifico(self, frase):
        assert detect_list_intent(frase) is False


class TestAliasesFoneticos:
    """O modelo não tem "podcast" no vocabulário: sempre escreve "pode se"."""

    ALIASES = {"pode se": "podcast", "de pode": "de podcast"}

    def test_corrige_podcast(self):
        assert apply_phrase_aliases("pode se de inteligencia", self.ALIASES) == (
            "podcast de inteligencia"
        )

    def test_corrige_dentro_da_frase(self):
        assert apply_phrase_aliases("mostrar lista de pode", self.ALIASES) == (
            "mostrar lista de podcast"
        )

    def test_respeita_limite_de_palavra(self):
        """"pode ser" é uma frase comum e não pode virar "podcast"."""
        assert apply_phrase_aliases("pode ser que sim", self.ALIASES) == "pode ser que sim"

    def test_sem_aliases_nao_altera(self):
        assert apply_phrase_aliases("texto qualquer", {}) == "texto qualquer"

    def test_troca_habilita_deteccao_de_tipo(self):
        corrigido = apply_phrase_aliases("pode se de inteligencia", self.ALIASES)
        assert detect_type(corrigido)[0] == "audio"
