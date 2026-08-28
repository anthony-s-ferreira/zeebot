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
    STOPWORDS,
    TYPE_KEYWORDS,
    apply_synonyms,
    detect_type,
    normalize,
)

from ..utils.fuzzy import HAS_RAPIDFUZZ as _HAS_RAPIDFUZZ, fuzz as _fuzz

log = logging.getLogger(__name__)

STATUS_OPEN = "open"
STATUS_MULTIPLE = "multiple"
STATUS_NOT_FOUND = "not_found"
STATUS_OPEN_LIST = "open_list"


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
            "status": self.status,
            "confidence": self.confidence,
            "resource": self.best.resource.to_dict() if self.best else None,
            "candidates": [c.to_dict() for c in self.candidates[:limit]],
        }


def _type_words() -> set:
    words = set()
    for entries in TYPE_KEYWORDS.values():
        words.update(normalize(word) for word in entries)
    return words


_TYPE_WORDS = _type_words()


def _content_tokens(text: str, synonyms: Dict[str, str]) -> List[str]:
    """Tokens que carregam o *assunto* — sem stopwords e sem palavras de tipo."""
    normalized = apply_synonyms(normalize(text), synonyms)
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
    def search(self, text: str, resources: Optional[Sequence[Resource]] = None) -> MatchResult:
        detected_type, type_hits = detect_type(text or "")
        tokens = _content_tokens(text or "", self.synonyms)
        cleaned = " ".join(tokens)

        pool = list(resources) if resources is not None else self.library.all()

        if not pool:
            return MatchResult(text or "", cleaned, detected_type, STATUS_NOT_FOUND, [])

        # "quero ver vídeos" — só o tipo, sem assunto: abre a listagem.
        if not tokens:
            if detected_type in VALID_TYPES:
                log.info("comando de listagem detectado: tipo=%s (%s)", detected_type, type_hits)
                return MatchResult(text or "", cleaned, detected_type, STATUS_OPEN_LIST, [])
            return MatchResult(text or "", cleaned, detected_type, STATUS_NOT_FOUND, [])

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
            return MatchResult(text or "", cleaned, detected_type, status, candidates)

        if runner_up and runner_up.score >= self.threshold and (best.score - runner_up.score) < self.margin:
            ambiguous = [c for c in candidates if c.score >= self.threshold][: self.max_suggestions]
            log.info(
                "resultado ambíguo: %s",
                ", ".join(f"{c.resource.id}={c.score:.1f}" for c in ambiguous),
            )
            return MatchResult(text or "", cleaned, detected_type, STATUS_MULTIPLE, ambiguous)

        log.info(
            "recurso selecionado: %s (%s) score=%.1f tipo=%s",
            best.resource.id, best.resource.titulo, best.score, detected_type or "-",
        )
        return MatchResult(text or "", cleaned, detected_type, STATUS_OPEN, candidates)
