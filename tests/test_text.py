"""Normalização de texto: acentos, maiúsculas, pontuação e tipos."""

from app.utils.text import (
    apply_synonyms,
    clean_query,
    detect_type,
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
