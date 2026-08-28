"""Barramento de eventos backend -> frontend (usado pelo SSE).

Escolha arquitetural: Server-Sent Events.  É unidirecional (que é exatamente o
que precisamos), roda sobre HTTP simples, reconecta sozinho no navegador e não
exige nenhuma dependência extra no Raspberry Pi — ao contrário de WebSockets.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

MAX_QUEUE_SIZE = 64


class Subscriber:
    """Fila de um cliente SSE."""

    _ids = itertools.count(1)

    def __init__(self, maxsize: int = MAX_QUEUE_SIZE) -> None:
        self.id = next(self._ids)
        self.queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=maxsize)

    def put(self, event: Dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            # Cliente lento: descarta o evento mais antigo para manter o mais novo.
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(event)
            except queue.Empty:  # pragma: no cover - corrida improvável
                pass

    def get(self, timeout: float) -> Optional[Dict[str, Any]]:
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None


class EventBus:
    """Publicação para N assinantes, com histórico do último evento por tipo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: List[Subscriber] = []
        self._sequence = 0

    def subscribe(self) -> Subscriber:
        subscriber = Subscriber()
        with self._lock:
            self._subscribers.append(subscriber)
            count = len(self._subscribers)
        log.debug("SSE: cliente %s conectado (%s ativos)", subscriber.id, count)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)
            count = len(self._subscribers)
        log.debug("SSE: cliente %s desconectado (%s ativos)", subscriber.id, count)

    def publish(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            self._sequence += 1
            event = {
                "seq": self._sequence,
                "type": event_type,
                "ts": time.time(),
                "data": payload or {},
            }
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(event)
        log.debug("evento publicado: %s (%s assinantes)", event_type, len(subscribers))
        return event

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)
