"""
Shared helpers for ChromaDB-backed pattern layers (Issue #315).

Chroma resolves a collection *name* to a server-side UUID exactly once --
when get_or_create_collection() is called -- and the returned Collection
object is pinned to that UUID for its lifetime. Layers in this package
cache that object across requests (see CoreAnchorsChromaLayer._collection,
TechRAGLayer._collection) so repeated calls avoid a network round trip.

That cache goes stale whenever the collection is recreated under a NEW
UUID without the long-lived pps server process being restarted:

- A host/container reboot that lost (or re-created) the ChromaDB volume.
- Another process (or our own anchor_resync()) running delete_collection()
  + create_collection() on the same name.

Once stale, every call on the cached handle raises Chroma's
"Collection [<uuid>] does not exist" error even though the collection is
perfectly healthy *by name*. This module provides a small retry helper:
resolve the collection, try the operation, and on a missing-collection
error drop the cache, re-resolve by name, and retry exactly once.
"""
from __future__ import annotations

from typing import Callable, TypeVar

import chromadb.errors as chroma_errors

T = TypeVar("T")

# Exception types ChromaDB itself raises when a collection UUID is gone.
# NotFoundError is the documented/typed case (raised both by the embedded
# segment API and re-raised client-side from the HTTP client's error-body
# mapping). InvalidUUIDError covers a malformed/garbage UUID. ValueError is
# included because older/embedded code paths document "raises ValueError if
# the collection does not exist" instead of a typed Chroma exception.
MISSING_COLLECTION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    chroma_errors.NotFoundError,
    chroma_errors.InvalidUUIDError,
    ValueError,
)


def is_missing_collection_error(exc: BaseException) -> bool:
    """True if `exc` looks like Chroma reporting a dead collection handle."""
    if isinstance(exc, MISSING_COLLECTION_EXCEPTIONS):
        return True
    msg = str(exc).lower()
    return "does not exist" in msg and "collection" in msg


def call_with_collection_retry(
    get_collection: Callable[..., object],
    op: Callable[[object], T],
    *,
    on_stale: Callable[[BaseException], None] | None = None,
) -> T:
    """
    Run `op(collection)` against `get_collection()`'s current handle.

    On a missing-collection error, call `get_collection(force_refresh=True)`
    to re-resolve the collection by name and retry `op` exactly once. Any
    other exception, or a second failure, propagates to the caller.

    Args:
        get_collection: callable taking an optional `force_refresh` kwarg
            that returns the (possibly cached) collection handle.
        op: the operation to run against the collection handle.
        on_stale: optional callback invoked with the caught exception when
            a stale handle is detected (e.g. for logging).
    """
    collection = get_collection()
    try:
        return op(collection)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, filtered below
        if not is_missing_collection_error(exc):
            raise
        if on_stale is not None:
            on_stale(exc)
        collection = get_collection(force_refresh=True)
        return op(collection)
