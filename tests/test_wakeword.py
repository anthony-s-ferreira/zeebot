"""Detecção da wakeword: variações aceitas, recusas e camadas de decisão."""

import json

import pytest

from app.config import BASE_DIR, Config
from app.voice.wakeword import WakewordDetector, build_grammar


@pytest.fixture
def detector():
    """Detector com a configuração real do projeto (sem cooldown)."""
    config = Config(BASE_DIR / "config" / "config.json").get("voice.wakeword")
    config["cooldown_seconds"] = 0
    return WakewordDetector(config)


class TestVariacoesAceitas:
    """Tudo que o Vosk costuma escrever quando o usuário diz "Oi, Zee"."""

    @pytest.mark.parametrize(
        "fala",
        [
            "oi zee", "Oi, Zee!", "OI ZEE", "oi  zee",
            "oi zi", "oi zí", "oi zé", "oi ze", "oi zii", "oi zzi",
            "oi z e", "oi ze e", "oi zeh", "oi zey", "oi zin", "oi zeca",
            "oizee", "oizi",
            "ei zee", "ei zi", "ei zí",
            "olá zee", "ola zi", "alô zi", "opa zi",
            "ôi zêe",
        ],
    )
    def test_aceita(self, detector, fala):
        assert detector.matches(fala), f"deveria aceitar {fala!r}: {detector.explain(fala)}"


class TestRecusas:
    """Nem "oi" sozinho, nem palavras que começam com z, disparam o assistente."""

    @pytest.mark.parametrize(
        "fala",
        [
            "", "oi", "olá", "bom dia", "boa tarde",
            "oi tudo bem", "oi professora", "oi gente", "oi galera", "olá pessoal",
            "oi zebra", "oi zero", "zebra", "oi cinema", "oi cebola",
            "oi z", "oi zona", "oi zélia",
            "oi joão", "oi maria", "oi bea", "oi amanda", "oi senhor", "oi dona",
            "quero assistir um vídeo", "abre o livro", "quero jogar o jogo do abc",
        ],
    )
    def test_recusa(self, detector, fala):
        assert not detector.matches(fala), f"não deveria aceitar {fala!r}: {detector.explain(fala)}"

    def test_recusa_frase_longa_mesmo_contendo_a_wakeword(self, detector):
        assert not detector.matches("então eu disse oi zee para o robô da escola")


class TestCamadas:
    """Lista de frases (exigente) × análise estrutural (tolerante)."""

    def test_estrutura_aceita_variacao_fora_da_lista(self, detector):
        info = detector.explain("opa zi")          # não está em phrases
        assert info["lista"] == 0.0
        assert info["estrutura"] >= detector.threshold
        assert info["aceito"] is True

    def test_lista_exige_similaridade_alta(self, detector):
        # "oi zero" é 83% parecido com "oi zé" — abaixo do phrase_threshold (90).
        info = detector.explain("oi zero")
        assert info["lista"] == 0.0
        assert info["estrutura"] == 0.0

    def test_nome_longo_e_rejeitado(self, detector):
        assert detector.structural_score("oi zebra") == (0.0, None)

    def test_nome_de_uma_letra_e_rejeitado(self, detector):
        """"oi z" é o que o ruído ambiente produz com a gramática ativa."""
        assert detector.structural_score("oi z") == (0.0, None)

    def test_prefixo_so_vale_com_tamanho_parecido(self, detector):
        """"zeh" conta como "ze"; "zero" e "zebra" não."""
        assert detector._name_score("zeh")[0] >= detector.name_threshold
        assert detector._name_score("zero")[0] < detector.name_threshold

    def test_saudacao_sozinha_nao_basta(self, detector):
        assert detector.structural_score("oi") == (0.0, None)

    def test_colapso_de_letras_repetidas(self, detector):
        assert detector.explain("oi zeee")["colapsado"] == "oi ze"
        assert detector.matches("oi zeee")

    def test_score_reflete_proximidade(self, detector):
        alto, _ = detector.score("oi zee")
        baixo, _ = detector.score("boa tarde")
        assert alto >= detector.threshold > baixo

    def test_estrutura_desativavel(self):
        detector = WakewordDetector(
            {"phrases": ["oi zee"], "cooldown_seconds": 0, "structural": {"enabled": False}}
        )
        assert detector.matches("oi zee") is True       # continua pela lista
        assert detector.matches("opa zi") is False      # sem a camada estrutural

    def test_nomes_configuraveis(self):
        detector = WakewordDetector(
            {
                "phrases": ["oi zee"],
                "cooldown_seconds": 0,
                "structural": {"names": ["ze", "zi", "si"]},
            }
        )
        assert detector.matches("oi si") is True        # forma extra reconhecida


class TestNomeSozinho:
    """Só o nome ("zé", sem o "oi") não pode disparar por padrão.

    Com a gramática ativa o reconhecedor encaixa qualquer conversa próxima na
    palavra mais parecida da lista — e um "zé" solto viraria falso positivo.
    """

    def test_recusado_por_padrao(self, detector):
        assert detector.allow_name_only is False
        assert detector.matches("zé") is False
        assert detector.matches("zi") is False

    def test_saudacao_continua_obrigatoria(self, detector):
        assert detector.matches("oi zé") is True

    def test_nao_aceita_qualquer_palavra_solta(self, detector):
        for fala in ["oi", "olá", "sim", "zebra", "casa", "bea"]:
            assert not detector.matches(fala), fala

    def test_pode_ser_ligado_na_configuracao(self):
        """Opt-in para microfones que cortam o início da fala."""
        detector = WakewordDetector(
            {
                "phrases": ["oi zee"],
                "cooldown_seconds": 0,
                "structural": {"allow_name_only": True},
            }
        )
        assert detector.matches("zé") is True
        assert detector.matches("casa") is False


class TestCooldown:
    def test_bloqueia_disparo_repetido(self):
        detector = WakewordDetector({"phrases": ["oi zee"], "cooldown_seconds": 30})
        assert detector.matches("oi zee") is True
        assert detector.matches("oi zee") is False      # dentro do cooldown
        detector.reset()
        assert detector.matches("oi zee") is True


class TestGramatica:
    def test_inclui_unk(self):
        grammar = json.loads(build_grammar(["oi zé", "oi zi"]))
        assert "[unk]" in grammar

    def test_preserva_acentos(self):
        """O vocabulário do modelo PT-BR tem "zé"/"zi"; "ze" e "zee" não existem."""
        grammar = json.loads(build_grammar(["Oi Zé!", "OI ZÉ", "olá zé"]))
        assert "oi zé" in grammar
        assert grammar.count("oi zé") == 1        # duplicata removida
        assert "oi ze" not in grammar             # acento não pode ser perdido

    def test_lista_vazia_tem_fallback(self):
        assert json.loads(build_grammar([])) == ["oi", "[unk]"]

    def test_gramatica_desativada(self):
        detector = WakewordDetector({"phrases": ["oi zee"], "use_grammar": False})
        assert detector.grammar is None

    def test_gramatica_do_config_padrao(self, detector):
        grammar = json.loads(detector.grammar)
        assert "oi zé" in grammar and "oi zi" in grammar and "[unk]" in grammar
