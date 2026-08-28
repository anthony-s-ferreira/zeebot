"""Aquecimento do pequeno modelo de linguagem local."""

from app.slm import LocalSLM


def test_slm_aquece_sem_gerar_resposta():
    slm = LocalSLM({"threads": 3})
    model = object()
    slm._load = lambda: model

    assert slm.warm_up() is True
    assert slm.last_error is None


def test_slm_registra_falha_de_aquecimento():
    slm = LocalSLM()

    def fail():
        raise RuntimeError("modelo ausente")

    slm._load = fail
    assert slm.warm_up() is False
    assert slm.last_error == "modelo ausente"


def test_slm_limita_resposta_a_uma_frase_e_ao_maximo_de_palavras():
    captured = {}

    class FakeModel:
        def create_chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "A resposta é Mercúrio, Vênus, Terra, Marte e Júpiter. "
                                "Depois ainda existem Saturno, Urano e Netuno."
                            )
                        }
                    }
                ]
            }

    slm = LocalSLM({"max_tokens": 48, "max_words": 5})
    slm._load = lambda: FakeModel()

    assert slm.answer("Quais são os planetas?") == "Mercúrio, Vênus, Terra, Marte e…"
    assert captured["max_tokens"] == 48
    assert "no maximo 5 palavras" in captured["messages"][0]["content"]


def test_slm_mantem_resposta_curta_sem_prefixo():
    class FakeModel:
        def create_chat_completion(self, **_kwargs):
            return {"choices": [{"message": {"content": "Vinte."}}]}

    slm = LocalSLM({"max_words": 24})
    slm._load = lambda: FakeModel()
    assert slm.answer("Quanto é dez mais dez?") == "Vinte."
