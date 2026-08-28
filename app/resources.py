"""Catálogo de recursos lido dinamicamente de ``data/recursos.json``.

Nada de conteúdo hardcoded na interface: o frontend sempre pede a lista à API,
e a API relê o arquivo quando o ``mtime`` muda.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)

#: Tipos suportados hoje.  Novos tipos entram aqui + no frontend (ICONS/render).
VALID_TYPES = ("video", "audio", "livro", "jogo")

#: Sinônimos aceitos no JSON para tolerar variações de digitação.
TYPE_ALIASES = {
    "video": "video", "vídeo": "video", "videos": "video", "vídeos": "video",
    "audio": "audio", "áudio": "audio", "audios": "audio", "áudios": "audio",
    "podcast": "audio", "livro": "livro", "livros": "livro", "book": "livro",
    "pdf": "livro", "jogo": "jogo", "jogos": "jogo", "game": "jogo",
}

_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_ALLOWED_SCHEMES = ("http", "https")


@dataclass
class Resource:
    id: str
    tipo: str
    titulo: str
    descricao: str = ""
    url: str = ""
    thumbnail: Optional[str] = None
    #: Outras formas de pedir o mesmo conteúdo por voz (ver ``aliases`` no JSON).
    aliases: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def embed_url(self) -> str:
        """URL pronta para ``<iframe>`` (converte links do YouTube)."""
        if self.tipo == "video":
            return to_embed_url(self.url)
        return self.url

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "id": self.id,
            "tipo": self.tipo,
            "titulo": self.titulo,
            "descricao": self.descricao,
            "url": self.url,
            "embed_url": self.embed_url,
            "thumbnail": self.thumbnail,
            "aliases": list(self.aliases),
        }
        payload.update({k: v for k, v in self.extra.items() if k not in payload})
        return payload


def to_embed_url(url: str) -> str:
    """Converte URLs do YouTube para o formato ``/embed/ID``.

    URLs que não sejam do YouTube voltam inalteradas.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if parsed.scheme and parsed.scheme not in _ALLOWED_SCHEMES:
        return url

    host = (parsed.netloc or "").lower()
    host = host[4:] if host.startswith("www.") else host
    video_id = None

    if host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [None])[0]
        elif parsed.path.startswith("/embed/"):
            return url
        elif parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/shorts/", 1)[1].split("/")[0]
        elif parsed.path.startswith("/live/"):
            video_id = parsed.path.split("/live/", 1)[1].split("/")[0]
    elif host == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/")[0]

    if video_id and _YOUTUBE_ID_RE.match(video_id):
        # rel=0 evita sugestões de terceiros; playsinline ajuda no Chromium.
        return f"https://www.youtube.com/embed/{video_id}?rel=0&playsinline=1"
    return url


def normalize_type(value: Any) -> Optional[str]:
    if not value:
        return None
    key = str(value).strip().lower()
    return TYPE_ALIASES.get(key)


def parse_resources(payload: Any) -> List[Resource]:
    """Valida o JSON e devolve apenas os recursos bem formados.

    Aceita ``{"recursos": [...]}`` ou uma lista pura.  Entradas inválidas são
    registradas e ignoradas — um recurso quebrado nunca derruba o catálogo.
    """
    if isinstance(payload, dict):
        items = payload.get("recursos") or payload.get("resources") or []
    elif isinstance(payload, list):
        items = payload
    else:
        log.error("recursos.json: formato inesperado (%s)", type(payload).__name__)
        return []

    resources: List[Resource] = []
    seen_ids = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            log.warning("recursos.json: item %s ignorado (não é objeto)", index)
            continue
        tipo = normalize_type(item.get("tipo"))
        if tipo not in VALID_TYPES:
            log.warning(
                "recursos.json: item %s ignorado (tipo inválido: %r)", index, item.get("tipo")
            )
            continue
        titulo = str(item.get("titulo") or "").strip()
        if not titulo:
            log.warning("recursos.json: item %s ignorado (sem título)", index)
            continue
        rid = str(item.get("id") or "").strip() or f"rec_auto_{index:03d}"
        if rid in seen_ids:
            log.warning("recursos.json: id duplicado %r — mantendo o primeiro", rid)
            continue
        url = str(item.get("url") or "").strip()
        if url and "://" in url and not url.lower().startswith(_ALLOWED_SCHEMES):
            log.warning("recursos.json: %s ignorado (esquema de URL não permitido)", rid)
            continue
        raw_aliases = item.get("aliases") or item.get("sinonimos") or []
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        aliases = [str(a).strip() for a in raw_aliases if str(a).strip()]

        seen_ids.add(rid)
        known = {"id", "tipo", "titulo", "descricao", "url", "thumbnail", "aliases", "sinonimos"}
        resources.append(
            Resource(
                id=rid,
                tipo=tipo,
                titulo=titulo,
                descricao=str(item.get("descricao") or "").strip(),
                url=url,
                thumbnail=(str(item["thumbnail"]).strip() if item.get("thumbnail") else None),
                aliases=aliases,
                extra={k: v for k, v in item.items() if k not in known},
            )
        )
    return resources


class ResourceLibrary:
    """Carrega e mantém o catálogo em memória, recarregando quando muda."""

    def __init__(self, path: Path, auto_reload: bool = True) -> None:
        self.path = Path(path)
        self.auto_reload = auto_reload
        self._lock = threading.RLock()
        self._resources: List[Resource] = []
        self._mtime: Optional[float] = None
        self._last_error: Optional[str] = None
        self.load(force=True)

    # ------------------------------------------------------------------ carga
    def load(self, force: bool = False) -> List[Resource]:
        with self._lock:
            try:
                mtime = self.path.stat().st_mtime
            except OSError as exc:
                if force or self._last_error is None:
                    log.error("não foi possível ler %s: %s", self.path, exc)
                self._last_error = str(exc)
                return list(self._resources)

            if not force and self._mtime == mtime:
                return list(self._resources)

            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                log.error("recursos.json inválido (%s) — mantendo catálogo anterior", exc)
                self._last_error = str(exc)
                self._mtime = mtime
                return list(self._resources)

            resources = parse_resources(payload)
            self._resources = resources
            self._mtime = mtime
            self._last_error = None
            log.info("catálogo carregado: %s recursos de %s", len(resources), self.path)
            return list(resources)

    def _ensure_fresh(self) -> None:
        if self.auto_reload:
            self.load(force=False)

    # ------------------------------------------------------------------ leitura
    def all(self) -> List[Resource]:
        self._ensure_fresh()
        with self._lock:
            return list(self._resources)

    def by_type(self, tipo: str) -> List[Resource]:
        normalized = normalize_type(tipo)
        if normalized is None:
            return []
        return [r for r in self.all() if r.tipo == normalized]

    def get(self, resource_id: str) -> Optional[Resource]:
        if not resource_id:
            return None
        target = str(resource_id).strip()
        for resource in self.all():
            if resource.id == target:
                return resource
        return None

    def counts(self) -> Dict[str, int]:
        counters = {tipo: 0 for tipo in VALID_TYPES}
        for resource in self.all():
            counters[resource.tipo] = counters.get(resource.tipo, 0) + 1
        return counters

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error
