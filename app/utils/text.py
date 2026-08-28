"""Normalização de texto em português para a busca tolerante."""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence

#: Palavras que não agregam significado ao comando falado.
STOPWORDS = {
    "a", "à", "as", "ao", "aos", "o", "os", "um", "uma", "uns", "umas",
    "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "por", "para", "pra", "pro", "com", "sem", "e", "ou", "que", "se",
    "eu", "me", "meu", "minha", "voce", "vc", "zee", "zé", "ze",
    "quero", "queria", "gostaria", "pode", "poderia", "favor", "por favor",
    "abra", "abre", "abrir", "abril", "inicia", "inicie", "iniciar",
    "coloca", "coloque", "colocar", "comeca", "comece", "comecar",
    "por", "poe", "poem", "bota", "bote", "botar", "chama", "chame", "chamar",
    "traz", "traga", "trazer", "procura", "procure", "procurar", "busca",
    "busque", "buscar", "acha", "ache", "achar", "encontra", "encontre",
    "carrega", "carregue", "roda", "rode", "rodar", "seleciona", "selecione",
    "entra", "entre", "entrar", "vamos", "vai", "bora", "agora", "favor",
    "agora", "ai", "la", "ali", "esse", "essa", "este", "esta", "isso",
    "aquele", "aquela", "o_seguinte", "sobre", "the",
}

#: Palavras que indicam a categoria desejada.
#:
#: São dois níveis: **fortes** (substantivos — "vídeo", "podcast", "livro",
#: "jogo") e **fracos** (verbos — "assistir", "ouvir", "ler", "mostrar").
#: Um substantivo sempre vence um verbo: em "mostra a lista de podcasts",
#: o "mostra" (vídeo) perde para "podcasts" (áudio).
TYPE_KEYWORDS_STRONG: Dict[str, Sequence[str]] = {
    "video": (
        "video", "videos", "videoaula", "videoaulas", "filme", "filmes",
        "youtube", "documentario", "documentarios", "aula", "aulas",
    ),
    "audio": (
        "audio", "audios", "podcast", "podcasts", "musica", "musicas",
        "som", "sons", "faixa", "faixas", "mp3", "radio", "audiobook",
    ),
    "livro": (
        "livro", "livros", "livrinho", "pdf", "pdfs", "ebook", "ebooks",
        "apostila", "apostilas", "leitura", "capitulo", "capitulos",
    ),
    "jogo": (
        "jogo", "jogos", "joguinho", "joguinhos", "game", "games",
        "brincadeira", "brincadeiras",
    ),
}

TYPE_KEYWORDS_WEAK: Dict[str, Sequence[str]] = {
    "video": ("assistir", "assista", "assiste", "ver", "veja", "vejo", "vendo", "reproduzir", "reproduza"),
    "audio": ("ouvir", "ouca", "ouve", "ouvindo", "escutar", "escute", "escuta", "escutando", "toca", "toque", "tocar"),
    "livro": ("ler", "leia", "le", "lendo", "estudar", "estude"),
    "jogo": ("jogar", "jogue", "joga", "jogando", "brincar", "brinque", "brinca", "play"),
}

#: Compatibilidade: união dos dois níveis.
TYPE_KEYWORDS: Dict[str, Sequence[str]] = {
    tipo: tuple(TYPE_KEYWORDS_STRONG[tipo]) + tuple(TYPE_KEYWORDS_WEAK[tipo])
    for tipo in TYPE_KEYWORDS_STRONG
}

#: Palavras que pedem a *listagem* em vez de um conteúdo específico.
LIST_KEYWORDS: Sequence[str] = (
    "lista", "listas", "listagem", "listar", "liste", "todos", "todas",
    "quais", "opcoes", "opcao", "catalogo", "biblioteca", "acervo",
    "menu", "tudo", "disponiveis", "disponivel", "existem", "tem",
)

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


def apply_phrase_aliases(text: str, aliases: Dict[str, str]) -> str:
    """Corrige trechos que o reconhecedor escreve errado, antes de tokenizar.

    O modelo PT-BR não tem "podcast" no vocabulário e sempre transcreve
    "pode se" / "de pode".  Aqui esses trechos voltam a ser ``podcast``.
    As chaves mais longas são aplicadas primeiro, e a troca respeita limites de
    palavra (``pode ser`` continua intocado).
    """
    if not aliases or not text:
        return text
    for origem in sorted(aliases, key=len, reverse=True):
        alvo = aliases[origem]
        origem_norm = normalize(origem)
        if not origem_norm:
            continue
        padrao = re.compile(rf"\b{re.escape(origem_norm)}\b")
        text = padrao.sub(normalize(alvo), text)
    return _SPACES_RE.sub(" ", text).strip()


def detect_list_intent(text: str) -> bool:
    """Verdadeiro quando o usuário pede a *lista* de uma categoria."""
    tokens = set(normalize(text).split())
    return bool(tokens & {normalize(word) for word in LIST_KEYWORDS})


def remove_stopwords(text: str, extra: Iterable[str] = ()) -> str:
    """Remove palavras irrelevantes, mas nunca devolve string vazia."""
    stop = set(STOPWORDS)
    stop.update(normalize(word) for word in extra if word)
    tokens = text.split()
    kept = [token for token in tokens if token not in stop]
    return " ".join(kept) if kept else text


def type_keywords_flat(source: Optional[Dict[str, Sequence[str]]] = None) -> Dict[str, str]:
    """Mapa palavra -> tipo, já normalizado."""
    flat: Dict[str, str] = {}
    for tipo, words in (source or TYPE_KEYWORDS).items():
        for word in words:
            flat[normalize(word)] = tipo
    return flat


def _detect_in_tier(tokens: List[str], tier: Dict[str, Sequence[str]]) -> tuple:
    flat = type_keywords_flat(tier)
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


def detect_type_detailed(text: str) -> tuple:
    """``(tipo, palavras_usadas, força)`` — força é ``"strong"``/``"weak"``/``None``.

    Substantivos ("podcast", "livro") têm prioridade sobre verbos ("mostrar",
    "ver"), porque o verbo costuma ser genérico: em "mostra a lista de
    podcasts" o tipo correto é ``audio``, não ``video``.  A força também serve
    de desempate entre as alternativas do reconhecedor.
    """
    tokens = normalize(text).split()
    tipo, palavras = _detect_in_tier(tokens, TYPE_KEYWORDS_STRONG)
    if tipo:
        return tipo, palavras, "strong"
    tipo, palavras = _detect_in_tier(tokens, TYPE_KEYWORDS_WEAK)
    return tipo, palavras, ("weak" if tipo else None)


def detect_type(text: str) -> tuple:
    """Detecta o tipo pedido e devolve ``(tipo, palavras_usadas)``."""
    tipo, palavras, _ = detect_type_detailed(text)
    return tipo, palavras


def clean_query(text: str, synonyms: Dict[str, str] | None = None) -> str:
    """Pipeline completo aplicado à fala do usuário antes da busca."""
    normalized = normalize(text)
    normalized = apply_synonyms(normalized, synonyms or {})
    type_words = set()
    for words in TYPE_KEYWORDS.values():
        type_words.update(normalize(word) for word in words)
    type_words.update(normalize(word) for word in LIST_KEYWORDS)
    return remove_stopwords(normalized, extra=type_words)
