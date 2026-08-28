#!/usr/bin/env python3
"""Teste da voz com fala sintética — desenvolvimento no macOS (sem Raspberry).

Usa o comando ``say`` do macOS para gerar áudio em português, alimenta o Vosk
com esse áudio e mostra a decisão completa: wakeword, transcrição e busca.
É a forma mais rápida de validar a cadeia de voz sem falar no microfone.

    venv/bin/python scripts/dev_say_test.py                 # matriz padrão
    venv/bin/python scripts/dev_say_test.py "Oi Zé" "Oi Zi"
    venv/bin/python scripts/dev_say_test.py --comando "quero ouvir o podcast de ia"
    venv/bin/python scripts/dev_say_test.py --voz Felipe

Requisitos: macOS (comando ``say``) e o modelo Vosk instalado.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import Config  # noqa: E402
from app.resources import ResourceLibrary  # noqa: E402
from app.voice.matcher import ResourceMatcher  # noqa: E402
from app.voice.recognizer import (  # noqa: E402
    CommandRecognizer,
    VoskEngine,
    result_hypotheses,
    result_text,
)
from app.voice.wakeword import WakewordDetector  # noqa: E402

#: Frases que DEVEM acionar / que NÃO podem acionar o assistente.
WAKEWORD_OK = ["Oi Zé", "Oi Zê", "Oi Zi", "Oi Zee", "Olá Zé", "Oi Zeca"]
WAKEWORD_NOK = [
    "Bom dia turma",
    "Oi professora",
    "Oi pessoal",
    "Quero assistir um vídeo",
    "Vamos jogar agora",
    "Oi gente tudo bem",
]
#: ``(frase, resultado esperado)`` — id do recurso, ``LISTA:tipo`` ou ``MENU``.
COMANDOS = [
    ("quero assistir ao vídeo de introdução à inteligência artificial", "rec_001"),
    ("abre o vídeo de introdução à inteligência artificial", "rec_001"),
    ("coloca a aula de inteligência artificial", "rec_001"),
    ("quero ouvir o podcast de inteligência artificial", "rec_002"),
    ("toca o podcast de inteligência artificial", "rec_002"),
    ("bota o áudio de inteligência artificial", "rec_002"),
    ("abra o livro fundamentos de inteligência artificial", "rec_003"),
    ("quero ler fundamentos de inteligência artificial", "rec_003"),
    ("abre o pdf de fundamentos", "rec_003"),
    ("quero jogar o jogo do alfabeto", "rec_004"),
    ("abre o jogo das letras", "rec_004"),
    ("bora brincar com o alfabeto", "rec_004"),
    ("lista de vídeos", "LISTA:video"),
    ("mostra a lista de podcasts", "LISTA:audio"),
    ("lista de livros", "LISTA:livro"),
    ("lista de jogos", "LISTA:jogo"),
    ("quais jogos existem", "LISTA:jogo"),
    ("quero ver a lista de áudios", "LISTA:audio"),
    ("abre o menu", "MENU"),
]


def falar(frase: str, destino: Path, voz: str, silencio_ms: int = 600) -> None:
    """Gera um WAV 16 kHz mono com silêncio nas pontas (como um microfone real)."""
    bruto = destino.with_suffix(".raw.wav")
    subprocess.run(
        ["say", "-v", voz, "-o", str(bruto), "--data-format=LEI16@16000", frase],
        check=True,
        capture_output=True,
    )
    with wave.open(str(bruto), "rb") as entrada:
        params = entrada.getparams()
        quadros = entrada.readframes(entrada.getnframes())
    silencio = b"\x00\x00" * int(params.framerate * silencio_ms / 1000)
    with wave.open(str(destino), "wb") as saida:
        saida.setparams(params)
        saida.writeframes(silencio + quadros + silencio)
    bruto.unlink(missing_ok=True)


def transcrever(engine: VoskEngine, wav: Path, grammar: Optional[str]) -> str:
    """Melhor transcrição do arquivo (usado no estágio da wakeword)."""
    hipoteses = transcrever_alternativas(engine, wav, grammar, None)
    return hipoteses[0] if hipoteses else ""


def transcrever_alternativas(
    engine: VoskEngine,
    wav: Path,
    grammar: Optional[str] = None,
    captura: Optional[CommandRecognizer] = None,
) -> List[str]:
    """Todas as transcrições (N-best), como no estágio de comando."""
    recognizer = engine.create_recognizer(grammar)
    if captura is not None:
        captura.configure_recognizer(recognizer)
    with wave.open(str(wav), "rb") as arquivo:
        while True:
            dados = arquivo.readframes(4000)
            if not dados:
                break
            recognizer.AcceptWaveform(dados)
    return result_hypotheses(recognizer.FinalResult())


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste de voz com fala sintética (macOS)")
    parser.add_argument("frases", nargs="*", help="frases para testar como wakeword")
    parser.add_argument("--comando", action="append", default=[], help="frase de comando")
    parser.add_argument("--voz", default="Luciana", help="voz do say (padrão: Luciana, pt-BR)")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()

    if shutil.which("say") is None:
        print("ERRO: comando 'say' não encontrado (este script é para macOS).")
        return 1

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.disable(logging.INFO)

    config = Config(args.config)
    try:
        engine = VoskEngine(
            Config.resolve_path(config.get("voice.model_path")),
            int(config.get("voice.sample_rate", 16000)),
        )
        engine.load()
    except Exception as exc:
        print(f"ERRO ao carregar o modelo Vosk: {exc}")
        print("Rode: ./scripts/download_vosk_model.sh")
        return 1

    detector = WakewordDetector(config.section("voice").get("wakeword", {}))
    detector.cooldown = 0.0
    library = ResourceLibrary(Config.resolve_path(config.get("app.resources_file")))
    matcher = ResourceMatcher(library, config.section("matching"))

    tmp = Path(tempfile.mkdtemp(prefix="zee-say-"))
    wav = tmp / "fala.wav"
    falhas = 0

    def testar_wakeword(frase: str, deve_acionar: bool) -> None:
        nonlocal falhas
        falar(frase, wav, args.voz)
        texto = transcrever(engine, wav, detector.grammar)
        info = detector.explain(texto)
        acionou = info["aceito"]
        ok = acionou == deve_acionar
        falhas += 0 if ok else 1
        marca = "ACIONA" if acionou else "ignora"
        print(
            f"  {'OK ' if ok else 'FALHA'}  {frase!r:28} -> {texto!r:16} "
            f"score={info['score']:5.1f}  {marca}"
        )

    print(f"\nVoz do say: {args.voz}    Gramática: {detector.grammar}\n")

    frases_ok = args.frases or WAKEWORD_OK
    print("WAKEWORD — deve acionar")
    for frase in frases_ok:
        testar_wakeword(frase, True)

    if not args.frases:
        print("\nWAKEWORD — não pode acionar")
        for frase in WAKEWORD_NOK:
            testar_wakeword(frase, False)

    captura = CommandRecognizer(config.section("voice").get("command", {}))
    comandos = [(frase, None) for frase in args.comando] or COMANDOS
    acertos = 0
    print("\nCOMANDOS — transcrição (N-best) + busca")
    print(f"  {'falado':46} {'transcrito':40} resultado")
    print("  " + "-" * 108)
    for frase, esperado in comandos:
        falar(frase, wav, args.voz)
        hipoteses = transcrever_alternativas(engine, wav, None, captura)
        resultado = matcher.search_best(hipoteses)
        obtido = {
            "open_list": f"LISTA:{resultado.detected_type}",
            "open_menu": "MENU",
        }.get(resultado.status)
        if obtido is None:
            obtido = resultado.best.resource.id if resultado.best else resultado.status
        transcrito = hipoteses[0] if hipoteses else ""
        if esperado is None:
            marca = " "
        else:
            ok = obtido == esperado
            acertos += ok
            falhas += 0 if ok else 1
            marca = "OK " if ok else f"ERRO (esperado {esperado})"
        print(f"  {frase[:44]:46} {transcrito[:38]!r:40} {obtido:12} {marca}")

    total = sum(1 for _, esperado in comandos if esperado is not None)
    if total:
        print(f"\n  comandos corretos: {acertos}/{total}")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nFalhas totais: {falhas}\n")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
