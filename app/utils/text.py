"""Normalização de texto em português para a busca tolerante."""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Sequence

#: Palavras que não agregam significado ao comando falado.
STOPWORDS = {
    "a", "à", "as", "ao", "aos", "o", "os", "um", "uma", "uns", "umas",
    "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "por", "para", "pra", "pro", "com", "sem", "e", "ou", "que", "se",
    "eu", "me", "meu", "minha", "voce", "vc", "zee", "zé", "ze",
    "quero", "queria", "gostaria", "pode", "poderia", "favor", "por favor",
    "abra", "abre", "abrir", "inicia", "inicie", "iniciar", "coloca", "coloque",
    "comeca", "comece", "comecar", "por", "poe", "chama", "chamar",
    "agora", "ai", "la", "ali", "esse", "essa", "este", "esta", "isso",
    "aquele", "aquela", "o_seguinte", "sobre", "the",
}

#: Verbos/substantivos que indicam a categoria desejada.
TYPE_KEYWORDS: Dict[str, Sequence[str]] = {
    "video": (
        "video", "videos", "assistir", "assista", "ver", "veja", "vejo",
        "mostrar", "mostre", "filme", "filmes", "reproduzir", "reproduza",
        "youtube", "aula", "documentario",
    ),
    "audio": (
        "audio", "audios", "podcast", "podcasts", "ouvir", "ouca", "escutar",
        "escute", "musica", "musicas", "som", "faixa", "mp3", "radio",
    ),
    "livro": (
        "livro", "livros", "ler", "leia", "leitura", "pdf", "ebook",
        "apostila", "texto", "capitulo", "documento",
    ),
    "jogo": (
        "jogo", "jogos", "jogar", "brincar", "brincadeira", "game", "games",
        "joguinho", "play",
    ),
}

_PUNCTUATION_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_SPACES_RE = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    """Remove acentuação preservando as letras base."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", without_marks)


def normalize(text: str, keep_accents: bool = False) -> str:
    """Minúsculas, sem pontuação e com espaços normalizados.

    Por padrão também remove acentos (é o que a busca fuzzy quer).  Com
    ``keep_accents=True`` a acentuação é preservada — necessário para a
    gramática do Vosk, que só aceita palavras na grafia exata do modelo
    (``zé`` existe no vocabulário PT-BR; ``ze`` não).
    """
    if not text:
        return ""
    lowered = str(text).lower()
    if not keep_accents:
        lowered = strip_accents(lowered)
    lowered = _PUNCTUATION_RE.sub(" ", lowered)
    return _SPACES_RE.sub(" ", lowered).strip()


def collapse_repeats(text: str, max_repeat: int = 1) -> str:
    """Reduz letras repetidas: ``zee`` -> ``ze``, ``ziii`` -> ``zi``.

    O Vosk escreve a mesma fala de formas diferentes ("zee", "zi", "zii").
    Colapsar repetições faz todas convergirem para a mesma raiz.
    """
    if not text:
        return ""
    out: List[str] = []
    previous = ""
    count = 0
    for char in text:
        if char == previous:
            count += 1
            if count >= max_repeat:
                continue
        else:
            previous = char
            count = 0
        out.append(char)
    return "".join(out)


def tokenize(text: str) -> List[str]:
    normalized = normalize(text)
    return normalized.split() if normalized else []


def apply_synonyms(text: str, synonyms: Dict[str, str]) -> str:
    """Expande siglas/apelidos (ex.: ``ia`` -> ``inteligencia artificial``)."""
    if not synonyms:
        return text
    tokens = text.split()
    if not tokens:
        return text
    normalized_map = {normalize(k): normalize(v) for k, v in synonyms.items() if k}
    expanded: List[str] = []
    for token in tokens:
        expanded.append(normalized_map.get(token, token))
    return " ".join(expanded)


def remove_stopwords(text: str, extra: Iterable[str] = ()) -> str:
    """Remove palavras irrelevantes, mas nunca devolve string vazia."""
    stop = set(STOPWORDS)
    stop.update(normalize(word) for word in extra if word)
    tokens = text.split()
    kept = [token for token in tokens if token not in stop]
    return " ".join(kept) if kept else text


def type_keywords_flat() -> Dict[str, str]:
    """Mapa palavra -> tipo, já normalizado."""
    flat: Dict[str, str] = {}
    for tipo, words in TYPE_KEYWORDS.items():
        for word in words:
            flat[normalize(word)] = tipo
    return flat


def detect_type(text: str) -> tuple:
    """Detecta o tipo pedido e devolve ``(tipo, palavras_usadas)``.

    Retorna ``(None, [])`` quando nenhuma palavra-chave aparece, e resolve
    empates pela primeira palavra-chave encontrada na frase.
    """
    flat = type_keywords_flat()
    tokens = normalize(text).split()
    hits: Dict[str, List[str]] = {}
    order: List[str] = []
    for token in tokens:
        tipo = flat.get(token)
        if tipo:
            hits.setdefault(tipo, []).append(token)
            if tipo not in order:
                order.append(tipo)
    if not order:
        return None, []
    # Mais ocorrências vence; empate mantém a ordem de aparição na frase.
    best = max(order, key=lambda t: (len(hits[t]), -order.index(t)))
    return best, hits[best]


def clean_query(text: str, synonyms: Dict[str, str] | None = None) -> str:
    """Pipeline completo aplicado à fala do usuário antes da busca."""
    normalized = normalize(text)
    normalized = apply_synonyms(normalized, synonyms or {})
    type_words = set()
    for words in TYPE_KEYWORDS.values():
        type_words.update(normalize(word) for word in words)
    return remove_stopwords(normalized, extra=type_words)
