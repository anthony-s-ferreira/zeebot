#!/usr/bin/env python3
"""Ferramenta de calibração da voz do Zee.

Uso (sempre com o venv do projeto):

    venv/bin/python scripts/voice_test.py devices     # lista microfones
    venv/bin/python scripts/voice_test.py wakeword    # mostra o que o Vosk ouve
    venv/bin/python scripts/voice_test.py wake "oi zi"   # testa a wakeword sem microfone
    venv/bin/python scripts/voice_test.py vocab       # confere a gramática no modelo
    venv/bin/python scripts/voice_test.py command     # grava 1 comando e busca
    venv/bin/python scripts/voice_test.py match "quero ver o video de ia"

O modo ``wakeword`` é o mais importante: ele imprime o texto reconhecido e a
pontuação contra cada variação configurada.  Use-o para descobrir como o modelo
PT-BR escreve o seu "Oi, Zee" e ajuste ``voice.wakeword.phrases`` no
``config/config.json``.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.audio import detect_microphone, list_input_devices  # noqa: E402
from app.config import Config  # noqa: E402
from app.resources import ResourceLibrary  # noqa: E402
from app.voice.matcher import ResourceMatcher  # noqa: E402
from app.voice.mic import MicrophoneStream, rms  # noqa: E402
from app.voice.recognizer import CommandRecognizer, VoskEngine, result_text  # noqa: E402
from app.voice.wakeword import WakewordDetector  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)-20s %(message)s")


def cmd_devices(config: Config) -> int:
    devices = list_input_devices()
    if not devices:
        print("Nenhum dispositivo de entrada encontrado.")
        print("Verifique: arecord -l    |    sudo apt install libportaudio2")
        return 1
    print(f"{len(devices)} dispositivo(s) de entrada:\n")
    for device in devices:
        print(f"  [{device['index']:>2}] {device['name']}")
        print(f"       canais={device['channels']}  taxa padrão={device['default_samplerate']:.0f} Hz")
    available, name, index = detect_microphone(config.get("voice.input_device"))
    print(f"\nSelecionado: {name} (índice {index})" if available else "\nNenhum microfone utilizável.")
    print("Para fixar um dispositivo, ajuste voice.input_device no config/config.json")
    return 0


def _build_engine(config: Config) -> VoskEngine:
    engine = VoskEngine(
        Config.resolve_path(config.get("voice.model_path")),
        int(config.get("voice.sample_rate", 16000)),
    )
    engine.load()
    return engine


def cmd_wake(config: Config, textos: List[str]) -> int:
    """Testa a decisão da wakeword sobre textos, sem precisar de microfone."""
    detector = WakewordDetector(config.section("voice").get("wakeword", {}))
    detector.cooldown = 0.0

    if not textos:
        textos = [
            "oi zee", "oi zi", "oi zí", "oi zé", "oizee", "oi z", "ei zi", "olá zee",
            "oi", "oi tudo bem", "oi zebra", "oi zero", "bom dia", "oi professora",
        ]

    print(f"\nLimiar: {detector.threshold}   (lista >= {detector.phrase_threshold})")
    print(f"Variações : {detector.phrases}")
    print(f"Saudações : {list(detector.greetings)}")
    print(f"Nomes     : {list(detector.name_forms)} (até {detector.max_name_length} letras)\n")
    print(f"{'texto':26} {'colapsado':14} {'lista':>7} {'estrut':>7} {'final':>7}  resultado")
    print("-" * 82)
    for texto in textos:
        info = detector.explain(texto)
        veredito = "ACEITO" if info["aceito"] else "recusado"
        print(
            f"{texto!r:26} {info['colapsado']:14} {info['lista']:7.1f} "
            f"{info['estrutura']:7.1f} {info['score']:7.1f}  {veredito}"
            + (f"  ~ {info['match']}" if info["match"] else "")
        )
    print()
    return 0


def cmd_vocab(config: Config) -> int:
    """Verifica se as palavras da gramática existem no vocabulário do modelo.

    A gramática do Vosk só aceita palavras que o modelo conhece; as demais são
    ignoradas com um aviso e a frase inteira deixa de funcionar.  O modelo
    PT-BR conhece ``zé`` e ``zi``, mas **não** conhece ``ze`` nem ``zee``.
    """
    import json as _json
    import os

    detector = WakewordDetector(config.section("voice").get("wakeword", {}))
    engine = _build_engine(config)

    if not detector.grammar:
        print("Gramática desativada (voice.wakeword.use_grammar = false).")
        return 0

    palavras: List[str] = []
    for phrase in _json.loads(detector.grammar):
        if phrase == "[unk]":
            continue
        for palavra in phrase.split():
            if palavra not in palavras:
                palavras.append(palavra)

    def existe(palavra: str) -> bool:
        """Cria um reconhecedor com a palavra e observa o aviso do Vosk."""
        read_fd, write_fd = os.pipe()
        saved = os.dup(2)
        os.dup2(write_fd, 2)
        os.close(write_fd)
        try:
            engine.create_recognizer(_json.dumps([palavra, "[unk]"], ensure_ascii=False))
        finally:
            os.dup2(saved, 2)
            os.close(saved)
            saida = os.read(read_fd, 65536).decode(errors="replace")
            os.close(read_fd)
        return "missing in vocabulary" not in saida

    print(f"\nGramática: {detector.grammar}\n")
    faltando = []
    for palavra in palavras:
        ok = existe(palavra)
        print(f"  {'OK ' if ok else 'AUSENTE'}  {palavra}")
        if not ok:
            faltando.append(palavra)

    print()
    if faltando:
        print(f"Palavras fora do vocabulário do modelo: {faltando}")
        print("Remova-as de voice.wakeword.grammar_phrases (a grafia importa:")
        print("o modelo PT-BR conhece 'zé' e 'zi', mas não 'ze' nem 'zee').")
        return 1
    print("Todas as palavras da gramática existem no modelo.")
    return 0


def cmd_wakeword(config: Config, seconds: float) -> int:
    detector = WakewordDetector(config.section("voice").get("wakeword", {}))
    engine = _build_engine(config)
    recognizer = engine.create_recognizer(detector.grammar)

    _, name, index = detect_microphone(config.get("voice.input_device"))
    stream = MicrophoneStream(
        int(config.get("voice.sample_rate", 16000)),
        int(config.get("voice.block_size", 4000)),
        index,
    )
    print(f"\nMicrofone: {name}")
    print(f"Gramática: {detector.grammar}")
    print(f"Variações aceitas: {detector.phrases}")
    print(f"Formas do nome: {list(detector.name_forms)}")
    print(f"Limiar: {detector.threshold}\n")
    print(f'Fale "Oi, Zee" algumas vezes. Ctrl+C para sair. ({seconds:.0f}s)\n')

    stream.open()
    deadline = time.time() + seconds
    try:
        while time.time() < deadline:
            data = stream.read()
            level = rms(data)
            if recognizer.AcceptWaveform(data):
                text = result_text(recognizer.Result())
                if text:
                    info = detector.explain(text)
                    hit = "  <<< WAKEWORD" if info["aceito"] else ""
                    print(
                        f"  final   rms={level:6.0f}  texto={text!r:26} "
                        f"lista={info['lista']:5.1f} estrut={info['estrutura']:5.1f} "
                        f"score={info['score']:5.1f}{hit}"
                    )
            else:
                partial = result_text(recognizer.PartialResult())
                if partial:
                    info = detector.explain(partial)
                    print(
                        f"  parcial rms={level:6.0f}  texto={partial!r:26} "
                        f"score={info['score']:5.1f} ~ {info['match']}"
                    )
    except KeyboardInterrupt:
        print("\ninterrompido")
    finally:
        stream.close()
    return 0


def cmd_command(config: Config) -> int:
    engine = _build_engine(config)
    recognizer = engine.create_recognizer(None)
    capture = CommandRecognizer(config.section("voice").get("command", {}), int(config.get("voice.sample_rate", 16000)))

    _, name, index = detect_microphone(config.get("voice.input_device"))
    stream = MicrophoneStream(
        int(config.get("voice.sample_rate", 16000)),
        int(config.get("voice.block_size", 4000)),
        index,
    )
    print(f"\nMicrofone: {name}")
    print("Fale o comando agora (ex.: 'quero assistir ao vídeo de introdução à inteligência artificial')\n")
    stream.open()
    try:
        text, metrics = capture.capture(stream, recognizer)
    finally:
        stream.close()

    print(f"\nTranscrição: {text!r}")
    print(f"Métricas   : {metrics}")
    if text:
        return cmd_match(config, text)
    print("Nada foi reconhecido. Dicas: aproxime-se do microfone e verifique o volume (alsamixer).")
    return 1


def cmd_match(config: Config, text: str) -> int:
    library = ResourceLibrary(Config.resolve_path(config.get("app.resources_file")))
    matcher = ResourceMatcher(library, config.section("matching"))
    result = matcher.search(text)

    print(f"\nConsulta normalizada : {result.cleaned_query!r}")
    print(f"Tipo detectado       : {result.detected_type}")
    print(f"Status               : {result.status}")
    print(f"Confiança            : {result.confidence}")
    print("\nRanking:")
    for candidate in result.candidates[:6]:
        marker = "->" if candidate is result.best else "  "
        print(
            f"  {marker} {candidate.score:5.1f}  {candidate.resource.id}  "
            f"[{candidate.resource.tipo}] {candidate.resource.titulo}"
        )
    print(f"\nLimiar configurado: {matcher.threshold} | margem de ambiguidade: {matcher.margin}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibração da voz do Zee")
    parser.add_argument(
        "command", choices=["devices", "wakeword", "wake", "vocab", "command", "match"]
    )
    parser.add_argument("text", nargs="*", help="texto para os modos match/wake")
    parser.add_argument("--seconds", type=float, default=60.0, help="duração do modo wakeword")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()

    config = Config(args.config)
    try:
        if args.command == "devices":
            return cmd_devices(config)
        if args.command == "wake":
            return cmd_wake(config, args.text)
        if args.command == "vocab":
            return cmd_vocab(config)
        if args.command == "wakeword":
            return cmd_wakeword(config, args.seconds)
        if args.command == "command":
            return cmd_command(config)
        if args.command == "match":
            if not args.text:
                parser.error("informe o texto: voice_test.py match \"quero ver o vídeo de ia\"")
            return cmd_match(config, " ".join(args.text))
    except Exception as exc:
        print(f"\nERRO: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
