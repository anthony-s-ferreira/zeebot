"""Busca tolerante de recursos a partir da fala transcrita.

Pipeline: normalização -> sinônimos -> detecção de tipo -> remoção de palavras
irrelevantes -> similaridade fuzzy (RapidFuzz) -> score 0-100 -> decisão.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..resources import Resource, VALID_TYPES
from ..utils.text import (
    LIST_KEYWORDS,
    STOPWORDS,
    TYPE_KEYWORDS,
    apply_phrase_aliases,
    apply_synonyms,
    detect_list_intent,
    detect_type_detailed,
    normalize,
)

from ..utils.fuzzy import HAS_RAPIDFUZZ as _HAS_RAPIDFUZZ, fuzz as _fuzz

log = logging.getLogger(__name__)

STATUS_OPEN = "open"
STATUS_MULTIPLE = "multiple"
STATUS_NOT_FOUND = "not_found"
STATUS_OPEN_LIST = "open_list"
STATUS_OPEN_MENU = "open_menu"


@dataclass
class Candidate:
    resource: Resource
    score: float
    title_score: float
    description_score: float
    type_match: Optional[bool]

    def to_dict(self) -> Dict[str, Any]:
        payload = self.resource.to_dict()
        payload["score"] = round(self.score, 1)
        payload["scores"] = {
            "titulo": round(self.title_score, 1),
            "descricao": round(self.description_score, 1),
            "tipo": self.type_match,
        }
        return payload


@dataclass
class MatchResult:
    query: str
    cleaned_query: str
    detected_type: Optional[str]
    status: str
    candidates: List[Candidate] = field(default_factory=list)
    #: "strong" (substantivo, ex.: "podcast") ou "weak" (verbo, ex.: "ver").
    type_strength: Optional[str] = None

    @property
    def best(self) -> Optional[Candidate]:
        return self.candidates[0] if self.candidates else None

    @property
    def confidence(self) -> float:
        return round(self.candidates[0].score, 1) if self.candidates else 0.0

    def to_dict(self, limit: int = 4) -> Dict[str, Any]:
        return {
            "query": self.query,
            "normalized_query": self.cleaned_query,
            "detected_type": self.detected_type,
            "type_strength": self.type_strength,
            "status": self.status,
            "confidence": self.confidence,
            "resource": self.best.resource.to_dict() if self.best else None,
            "candidates": [c.to_dict() for c in self.candidates[:limit]],
        }


def _type_words() -> set:
    words = set()
    for entries in TYPE_KEYWORDS.values():
        words.update(normalize(word) for word in entries)
    words.update(normalize(word) for word in LIST_KEYWORDS)
    return words


_TYPE_WORDS = _type_words()


def _content_tokens(
    text: str, synonyms: Dict[str, str], aliases: Optional[Dict[str, str]] = None
) -> List[str]:
    """Tokens que carregam o *assunto* — sem stopwords e sem palavras de tipo."""
    normalized = apply_phrase_aliases(normalize(text), aliases or {})
    normalized = apply_synonyms(normalized, synonyms)
    return [
        token
        for token in normalized.split()
        if token not in STOPWORDS and token not in _TYPE_WORDS and len(token) > 1
    ]


class ResourceMatcher:
    """Aplica o score configurado sobre o catálogo."""

    def __init__(self, library, config: Optional[Dict[str, Any]] = None) -> None:
        self.library = library
        self.configure(config or {})
        if not _HAS_RAPIDFUZZ:
            log.warning("RapidFuzz indisponível — usando fallback da stdlib (mais lento)")

    def configure(self, config: Dict[str, Any]) -> None:
        self.threshold = float(config.get("confidence_threshold", 70))
        self.margin = float(config.get("ambiguity_margin", 8))
        self.max_suggestions = int(config.get("max_suggestions", 4))
        self.title_weight = float(config.get("title_weight", 0.8))
        self.description_weight = float(config.get("description_weight", 0.2))
        self.type_bonus = float(config.get("type_bonus", 12))
        self.type_penalty = float(config.get("type_penalty", 25))
        raw_synonyms = config.get("synonyms") or {}
        self.synonyms = {str(k): str(v) for k, v in raw_synonyms.items()}
        raw_aliases = config.get("phonetic_aliases") or {}
        self.phonetic_aliases = {str(k): str(v) for k, v in raw_aliases.items()}

    # ------------------------------------------------------------------ score
    @staticmethod
    def _token_f1(query_tokens: List[str], target_tokens: List[str]) -> float:
        """Cobertura mútua entre as palavras do comando e as do título.

        Evita o efeito colateral clássico do ``token_set_ratio``: "inteligência
        artificial" e "fundamentos de inteligência artificial" seriam ambos 100
        para o comando "abra fundamentos de inteligência artificial".  Aqui, o
        título que cobre *mais* palavras do comando pontua mais.
        """
        if not query_tokens or not target_tokens:
            return 0.0

        def coverage(source: List[str], reference: List[str]) -> float:
            hits = 0
            for token in source:
                best = max((float(_fuzz.ratio(token, other)) for other in reference), default=0.0)
                if best >= 80.0:
                    hits += 1
            return hits / len(source)

        precision = coverage(query_tokens, target_tokens)
        recall = coverage(target_tokens, query_tokens)
        if precision + recall == 0:
            return 0.0
        return 100.0 * (2 * precision * recall) / (precision + recall)

    def _similarity(self, query_tokens: List[str], target_tokens: List[str]) -> float:
        """Mistura similaridade textual (RapidFuzz) com cobertura de palavras."""
        if not query_tokens or not target_tokens:
            return 0.0
        query = " ".join(query_tokens)
        target = " ".join(target_tokens)
        weighted = float(_fuzz.WRatio(query, target))
        coverage = self._token_f1(query_tokens, target_tokens)
        return 0.5 * weighted + 0.5 * coverage

    def score_resource(
        self, resource: Resource, query_tokens: List[str], detected_type: Optional[str]
    ) -> Candidate:
        title_tokens = _content_tokens(resource.titulo, self.synonyms) or normalize(
            resource.titulo
        ).split()
        desc_tokens = _content_tokens(resource.descricao, self.synonyms)

        title_score = self._similarity(query_tokens, title_tokens)
        # Apelidos valem como título: é assim que "jogo do alfabeto" encontra o
        # "Jogo do ABC" (o modelo de voz não transcreve siglas soletradas).
        for alias in resource.aliases:
            alias_tokens = _content_tokens(alias, self.synonyms)
            if alias_tokens:
                title_score = max(title_score, self._similarity(query_tokens, alias_tokens))
        desc_score = self._similarity(query_tokens, desc_tokens)

        # A descrição só pode *ajudar*: ela nunca derruba um título muito bom.
        score = max(
            title_score,
            self.title_weight * title_score + self.description_weight * desc_score,
        )

        type_match: Optional[bool] = None
        if detected_type:
            type_match = resource.tipo == detected_type
            score += self.type_bonus if type_match else -self.type_penalty

        score = max(0.0, min(100.0, score))
        return Candidate(resource, score, title_score, desc_score, type_match)

    # ----------------------------------------------------------------- busca
    def corrected_query(self, text: str) -> str:
        """Corrige formas conhecidas do reconhecimento antes do roteamento."""
        return apply_phrase_aliases(normalize(text or ""), self.phonetic_aliases)

    def search(self, text: str, resources: Optional[Sequence[Resource]] = None) -> MatchResult:
        # Corrige o que o reconhecedor escreve errado antes de qualquer análise
        # ("pode se" -> "podcast"): a detecção de tipo depende disso.
        corrected = self.corrected_query(text)
        detected_type, type_hits, type_strength = detect_type_detailed(corrected)
        wants_list = detect_list_intent(corrected)
        tokens = _content_tokens(corrected, self.synonyms, self.phonetic_aliases)
        cleaned = " ".join(tokens)

        pool = list(resources) if resources is not None else self.library.all()

        # "lista de vídeos", "quais jogos existem", "mostra todos os livros"
        if wants_list:
            if detected_type in VALID_TYPES:
                log.info("pedido de listagem: tipo=%s (%s)", detected_type, type_hits)
                return MatchResult(
                    text or "", cleaned, detected_type, STATUS_OPEN_LIST, [], type_strength
                )
            log.info("pedido de listagem sem tipo definido — abrindo o menu")
            return MatchResult(text or "", cleaned, None, STATUS_OPEN_MENU, [], None)

        if not pool:
            return MatchResult(text or "", cleaned, detected_type, STATUS_NOT_FOUND, [], type_strength)

        # "quero ver vídeos" — só o tipo, sem assunto: abre a listagem.
        if not tokens:
            if detected_type in VALID_TYPES:
                log.info("comando de listagem detectado: tipo=%s (%s)", detected_type, type_hits)
                return MatchResult(
                    text or "", cleaned, detected_type, STATUS_OPEN_LIST, [], type_strength
                )
            return MatchResult(text or "", cleaned, detected_type, STATUS_NOT_FOUND, [], type_strength)

        candidates = [self.score_resource(r, tokens, detected_type) for r in pool]
        candidates.sort(key=lambda c: c.score, reverse=True)

        best = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None

        if best.score < self.threshold:
            status = STATUS_OPEN_LIST if detected_type in VALID_TYPES else STATUS_NOT_FOUND
            if status == STATUS_OPEN_LIST:
                log.info(
                    "nenhum título acima do limiar (%.1f < %s) — abrindo listagem de %s",
                    best.score, self.threshold, detected_type,
                )
            else:
                log.info("nenhum recurso acima do limiar (melhor=%.1f)", best.score)
            return MatchResult(text or "", cleaned, detected_type, status, candidates, type_strength)

        if runner_up and runner_up.score >= self.threshold and (best.score - runner_up.score) < self.margin:
            ambiguous = [c for c in candidates if c.score >= self.threshold][: self.max_suggestions]
            log.info(
                "resultado ambíguo: %s",
                ", ".join(f"{c.resource.id}={c.score:.1f}" for c in ambiguous),
            )
            return MatchResult(
                text or "", cleaned, detected_type, STATUS_MULTIPLE, ambiguous, type_strength
            )

        log.info(
            "recurso selecionado: %s (%s) score=%.1f tipo=%s",
            best.resource.id, best.resource.titulo, best.score, detected_type or "-",
        )
        return MatchResult(
            text or "", cleaned, detected_type, STATUS_OPEN, candidates, type_strength
        )

    #: Ordem de preferência quando as alternativas do reconhecedor divergem.
    #: Abrir o conteúdo > abrir a listagem certa > pedir para escolher >
    #: cair no menu genérico > não achar nada.
    _STATUS_RANK = {
        STATUS_OPEN: 5,
        STATUS_OPEN_LIST: 4,
        STATUS_MULTIPLE: 3,
        STATUS_OPEN_MENU: 2,
        STATUS_NOT_FOUND: 1,
    }
    _STRENGTH_RANK = {"strong": 2, "weak": 1, None: 0}

    def search_best(
        self, hypotheses: Sequence[str], resources: Optional[Sequence[Resource]] = None
    ) -> MatchResult:
        """Avalia várias transcrições (N-best do Vosk) e fica com a melhor.

        O reconhecedor devolve alternativas ordenadas por confiança acústica,
        mas a alternativa mais provável nem sempre é a que faz sentido para o
        catálogo — aqui vence a que encontra conteúdo com mais confiança.
        """
        textos = [h for h in dict.fromkeys(hypotheses or []) if h and h.strip()]
        if not textos:
            return MatchResult("", "", None, STATUS_NOT_FOUND, [])

        def chave(resultado: MatchResult):
            return (
                self._STATUS_RANK.get(resultado.status, 0),
                self._STRENGTH_RANK.get(resultado.type_strength, 0),
                resultado.confidence,
            )

        melhor = self.search(textos[0], resources)
        for texto in textos[1:]:
            atual = self.search(texto, resources)
            chave_atual, chave_melhor = chave(atual), chave(melhor)
            if chave_atual > chave_melhor:
                log.info("alternativa preferida: %r (%s)", texto, atual.status)
                melhor = atual
        return melhor
