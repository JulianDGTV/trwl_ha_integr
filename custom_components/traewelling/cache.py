"""Kleiner In-Memory-Cache mit Ablaufzeit und Zusammenfassen paralleler Anfragen.

Gleiche Anfragen innerhalb der Ablaufzeit – z. B. dieselbe Abfahrtstafel auf
Handy und iPad oder wiederholte Stationssuchen – gehen so nur einmal an
Träwelling. Laufen zwei identische Anfragen gleichzeitig, warten beide auf
dieselbe Antwort. Fehler werden nie gespeichert.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any


class TtlCache:
    """TTL-Cache mit Größenbegrenzung (älteste Einträge fliegen zuerst raus)."""

    def __init__(self, max_entries: int = 256) -> None:
        self._max = max_entries
        self._items: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._inflight: dict[Hashable, asyncio.Future[Any]] = {}

    def get(self, key: Hashable) -> tuple[bool, Any]:
        """(Treffer?, Wert) – abgelaufene Einträge zählen nicht."""
        item = self._items.get(key)
        if item is None:
            return False, None
        expires, value = item
        if expires < time.monotonic():
            self._items.pop(key, None)
            return False, None
        self._items.move_to_end(key)
        return True, value

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        self._items[key] = (time.monotonic() + ttl, value)
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def invalidate(self, predicate: Callable[[Hashable], bool] | None = None) -> None:
        """Alles bzw. alle passenden Schlüssel verwerfen."""
        if predicate is None:
            self._items.clear()
            return
        for key in [k for k in self._items if predicate(k)]:
            self._items.pop(key, None)

    async def get_or_fetch(
        self, key: Hashable, ttl: float, fetch: Callable[[], Awaitable[Any]]
    ) -> Any:
        hit, value = self.get(key)
        if hit:
            return value
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value = await fetch()
        except Exception as err:
            if not future.done():
                future.set_exception(err)
                future.exception()  # als abgerufen markieren (kein „never retrieved“)
            raise
        except BaseException:  # z. B. Abbruch – Wartende brechen mit ab
            future.cancel()
            raise
        else:
            self.set(key, value, ttl)
            if not future.done():
                future.set_result(value)
            return value
        finally:
            self._inflight.pop(key, None)
