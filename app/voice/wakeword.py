"""Detecção da wakeword "Oi, Zee".

O modelo PT-BR do Vosk não conhece a grafia *zee*.  Dependendo do microfone e
da pronúncia, ele escreve a mesma fala como "oi zé", "oi zi", "oi zii",
"oi zé", "oi z", "oizee"...  Por isso a detecção acontece em três camadas:

1. **Gramática do Vosk** — o reconhecedor do estágio 1 recebe uma lista fechada
   de frases, então nem tenta transcrever frases completas.  Isso derruba CPU e
   falsos positivos.
2. **Comparação fuzzy** com a lista de variações do ``config.json``.
3. **Análise estrutural** — a fala é quebrada em *saudação* + *nome*.  Vale como
   wakeword quando a saudação parece "oi/ei/olá" **e** o nome parece "zê/zi/z",
   depois de colapsar letras repetidas (``zee`` → ``ze``, ``zii`` → ``zi``) e
   remover acentos (``zí``/``zé`` → ``zi``/``ze``).

A camada 3 é o que faz "oi zee", "oi zi", "oi zí", "oi zé" e "oizee" caírem
todas no mesmo lugar sem precisar listar cada variação à mão.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..utils.fuzzy import fuzz
from ..utils.text import collapse_repeats, normalize

log = logging.getLogger(__name__)

#: Primeira parte da wakeword ("oi, ...").
DEFAULT_GREETINGS: Tuple[str, ...] = ("oi", "ei", "ai", "ola", "alo", "opa", "oe", "hei")

#: Segunda parte, já colapsada: "zee"/"zii"/"zí"/"zé" convergem para "ze"/"zi".
DEFAULT_NAME_FORMS: Tuple[str, ...] = ("ze", "zi", "zey", "zin", "zeca")

#: Nomes maiores que isso não são o "Zee" — barra "zebra", "zero", "senhor"...
MAX_NAME_LENGTH = 4

#: Nomes de uma letra só ("oi z") são o que o ruído ambiente costuma produzir.
MIN_NAME_LENGTH = 2


def build_grammar(phrases: Sequence[str]) -> str:
    """Monta a gramática JSON aceita pelo ``KaldiRecognizer``.

    **A acentuação é preservada de propósito**: a gramática do Vosk só aceita
    palavras que existam no vocabulário do modelo, e o modelo PT-BR conhece
    ``zé`` e ``zi`` — mas não ``ze`` nem ``zee``.  Palavras desconhecidas são
    ignoradas pelo Vosk com um aviso, deixando a frase inteira inútil.

    ``[unk]`` é obrigatório: sem ele o Vosk força qualquer ruído para dentro da
    lista e tudo vira wakeword.
    """
    cleaned: List[str] = []
    for phrase in phrases or []:
        normalized = normalize(phrase, keep_accents=True)
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
    if not cleaned:
        cleaned = ["oi"]
    return json.dumps(cleaned + ["[unk]"], ensure_ascii=False)


class WakewordDetector:
    """Decide se um texto reconhecido corresponde à wakeword."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.configure(config or {})
        self._last_detection = 0.0

    def configure(self, config: Dict[str, Any]) -> None:
        phrases = config.get("phrases") or ["oi zee"]
        if isinstance(phrases, str):
            phrases = [phrases]
        self.phrases = [normalize(p) for p in phrases if normalize(p)]
        self.threshold = float(config.get("fuzzy_threshold", 82))
        self.max_words = int(config.get("max_words", 4))
        self.cooldown = float(config.get("cooldown_seconds", 2.0))
        self.use_grammar = bool(config.get("use_grammar", True))
        self.grammar_phrases = config.get("grammar_phrases") or self.phrases
        # Mantido por compatibilidade de configuração; a comparação parcial foi
        # substituída pela análise estrutural, que é mais precisa.
        self.require_partial_match = bool(config.get("require_partial_match", True))

        structural = config.get("structural") or {}
        self.structural_enabled = bool(structural.get("enabled", True))
        self.greetings = tuple(
            normalize(g) for g in (structural.get("greetings") or DEFAULT_GREETINGS) if normalize(g)
        ) or DEFAULT_GREETINGS
        self.name_forms = tuple(
            collapse_repeats(normalize(n))
            for n in (structural.get("names") or DEFAULT_NAME_FORMS)
            if normalize(n)
        ) or DEFAULT_NAME_FORMS
        self.greeting_threshold = float(structural.get("greeting_threshold", 80))
        self.name_threshold = float(structural.get("name_threshold", 74))
        self.max_name_length = int(structural.get("max_name_length", MAX_NAME_LENGTH))
        self.min_name_length = int(structural.get("min_name_length", MIN_NAME_LENGTH))
        # Aceitar só o nome ("zé", sem o "oi") é tentador quando o início da
        # gravação corta a saudação — mas é perigoso: com a gramática ativa,
        # qualquer conversa ao redor acaba "encaixada" na palavra mais próxima
        # da lista, e um "zé" solto dispararia o assistente.  Fica desligado por
        # padrão; ligue apenas se o seu microfone realmente cortar o começo.
        self.allow_name_only = bool(structural.get("allow_name_only", False))
        self.name_only_threshold = float(structural.get("name_only_threshold", 90))
        # A lista de frases é exigente de propósito: quem tolera variação é a
        # camada estrutural.  Sem isso, "oi zero" casaria com "oi zé".
        self.phrase_threshold = float(config.get("phrase_threshold", 90))

    @property
    def grammar(self) -> Optional[str]:
        if not self.use_grammar:
            return None
        return build_grammar(self.grammar_phrases)

    # --------------------------------------------------------- camada 2: lista
    def phrase_score(self, normalized: str) -> Tuple[float, Optional[str]]:
        """Compara a fala inteira com as variações do ``config.json``.

        Usa apenas similaridade de string *completa* (nada de ``partial_ratio``):
        com frases curtas como "oi zé", uma comparação parcial daria ~85 para
        qualquer "oi ..." e o assistente dispararia sozinho.
        """
        if not normalized:
            return 0.0, None

        collapsed = collapse_repeats(normalized)
        no_space = collapsed.replace(" ", "")

        best_score = 0.0
        best_phrase: Optional[str] = None
        for phrase in self.phrases:
            phrase_collapsed = collapse_repeats(phrase)
            score = max(
                float(fuzz.ratio(normalized, phrase)),
                float(fuzz.ratio(collapsed, phrase_collapsed)),
                float(fuzz.ratio(no_space, phrase_collapsed.replace(" ", ""))),
            )
            if score > best_score:
                best_score, best_phrase = score, phrase

        if best_score < self.phrase_threshold:
            return 0.0, None
        return best_score, best_phrase

    # ---------------------------------------------------- camada 3: estrutura
    def _split_greeting(self, normalized: str) -> Optional[Tuple[str, str]]:
        """Separa a fala em ``(saudação, nome)``.

        Aceita tanto "oi zee" quanto "oizee" (o Vosk às vezes cola as palavras)
        e "oi z e" (letras soltas viram um nome só).
        """
        collapsed = collapse_repeats(normalized)
        tokens = collapsed.split()
        if not tokens:
            return None

        if len(tokens) == 1:
            token = tokens[0]
            for greeting in self.greetings:
                if token.startswith(greeting) and len(token) > len(greeting):
                    return greeting, token[len(greeting) :]
            return None

        # "oi z e" -> nome "ze"; "oi zee" -> "ze" (repetições já colapsadas)
        return tokens[0], collapse_repeats("".join(tokens[1:]))

    def _name_score(self, name: str) -> Tuple[float, Optional[str]]:
        """Quanto o trecho se parece com "Zee" (já colapsado e sem acento)."""
        if not name or not (self.min_name_length <= len(name) <= self.max_name_length):
            return 0.0, None
        best = 0.0
        matched: Optional[str] = None
        for form in self.name_forms:
            score = float(fuzz.ratio(name, form))
            if name == form:
                score = 100.0
            elif (name.startswith(form) or form.startswith(name)) and abs(
                len(name) - len(form)
            ) <= 1:
                # "zeh"/"zey" contam como "ze"; "zero"/"zebra" NÃO — o prefixo
                # só vale quando os tamanhos são praticamente iguais.
                score = max(score, 88.0)
            if score > best:
                best, matched = score, form
        return best, matched

    def structural_score(self, normalized: str) -> Tuple[float, Optional[str]]:
        """Pontua "saudação + nome" sem depender da grafia exata."""
        if not self.structural_enabled:
            return 0.0, None
        parts = self._split_greeting(normalized)
        if parts is None:
            # Só o nome ("zé"): desligado por padrão — veja o comentário em
            # configure().  Quando ligado, exige correspondência quase exata.
            if not self.allow_name_only:
                return 0.0, None
            name = collapse_repeats(normalized).replace(" ", "")
            name_score, matched = self._name_score(name)
            if name_score < max(self.name_only_threshold, self.name_threshold):
                return 0.0, None
            return name_score * 0.9, matched
        greeting, name = parts
        if not name:
            return 0.0, None

        greeting_score = max(
            (float(fuzz.ratio(greeting, candidate)) for candidate in self.greetings), default=0.0
        )
        if greeting_score < self.greeting_threshold:
            return 0.0, None

        # Nomes longos ("zebra", "zero", "cinema") não são o Zee.
        name_score, matched = self._name_score(name)
        if name_score < self.name_threshold:
            return 0.0, None

        # O nome pesa mais: é ele que distingue "oi, Zee" de um "oi" qualquer.
        total = 0.35 * greeting_score + 0.65 * name_score
        return total, f"{greeting} {matched}"

    # ------------------------------------------------------------------ match
    def score(self, text: str) -> Tuple[float, Optional[str]]:
        """Melhor pontuação (0-100) considerando lista e estrutura."""
        normalized = normalize(text)
        if not normalized:
            return 0.0, None
        phrase_score, phrase = self.phrase_score(normalized)
        struct_score, struct = self.structural_score(normalized)
        if struct_score > phrase_score:
            return struct_score, struct
        return phrase_score, phrase

    def matches(self, text: str) -> bool:
        """Aplica limiar, limite de palavras e cooldown."""
        normalized = normalize(text)
        if not normalized:
            return False
        if len(normalized.split()) > self.max_words:
            log.debug("wakeword descartada (frase longa): %r", normalized)
            return False

        score, phrase = self.score(normalized)
        if score < self.threshold:
            if score >= self.threshold - 15:
                log.debug("quase-wakeword: %r (%.1f < %.1f)", normalized, score, self.threshold)
            return False

        now = time.time()
        if now - self._last_detection < self.cooldown:
            log.debug("wakeword ignorada (cooldown): %r", normalized)
            return False

        self._last_detection = now
        log.info('wakeword detectada: "%s" ~ "%s" (%.1f)', normalized, phrase, score)
        return True

    def reset(self) -> None:
        self._last_detection = 0.0

    def explain(self, text: str) -> Dict[str, Any]:
        """Detalhamento usado pelo ``scripts/voice_test.py``."""
        normalized = normalize(text)
        phrase_score, phrase = self.phrase_score(normalized)
        struct_score, struct = self.structural_score(normalized)
        score, matched = self.score(normalized)
        return {
            "texto": normalized,
            "colapsado": collapse_repeats(normalized),
            "lista": round(phrase_score, 1),
            "lista_match": phrase,
            "estrutura": round(struct_score, 1),
            "estrutura_match": struct,
            "score": round(score, 1),
            "match": matched,
            "aceito": score >= self.threshold,
        }
