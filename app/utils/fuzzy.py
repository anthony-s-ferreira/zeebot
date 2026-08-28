"""Camada fina sobre o RapidFuzz com fallback para a stdlib.

O RapidFuzz é a implementação usada no Raspberry Pi (rápida, em C++).  O
fallback existe para que testes e ambientes de desenvolvimento continuem
funcionando mesmo sem a dependência compilada.
"""

from __future__ import annotations

from difflib import SequenceMatcher

try:
    from rapidfuzz import fuzz  # type: ignore

    HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover - caminho de fallback
    HAS_RAPIDFUZZ = False

    class _FallbackFuzz:
        @staticmethod
        def ratio(a: str, b: str) -> float:
            if not a or not b:
                return 0.0
            return SequenceMatcher(None, a, b).ratio() * 100.0

        @classmethod
        def partial_ratio(cls, a: str, b: str) -> float:
            if not a or not b:
                return 0.0
            short, long = (a, b) if len(a) <= len(b) else (b, a)
            window = len(short)
            best = 0.0
            for start in range(max(1, len(long) - window + 1)):
                best = max(best, cls.ratio(short, long[start : start + window]))
            return best

        @classmethod
        def token_set_ratio(cls, a: str, b: str) -> float:
            ta, tb = set(a.split()), set(b.split())
            if not ta or not tb:
                return 0.0
            common = ta & tb
            base = " ".join(sorted(common))
            rest_a = (base + " " + " ".join(sorted(ta - common))).strip()
            rest_b = (base + " " + " ".join(sorted(tb - common))).strip()
            scores = [cls.ratio(rest_a, rest_b)]
            if base:
                scores.append(cls.ratio(base, rest_a))
                scores.append(cls.ratio(base, rest_b))
            return max(scores)

        @classmethod
        def WRatio(cls, a: str, b: str) -> float:  # noqa: N802 - espelha a API
            return max(cls.ratio(a, b), cls.partial_ratio(a, b) * 0.9)

    fuzz = _FallbackFuzz()  # type: ignore[assignment]

__all__ = ["fuzz", "HAS_RAPIDFUZZ"]
