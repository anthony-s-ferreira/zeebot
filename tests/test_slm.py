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
