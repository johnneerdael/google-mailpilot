"""Time-boxed batch processing utilities for MCP tools."""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar

DEFAULT_TIME_LIMIT_SECONDS = 5.0

T = TypeVar("T")


@dataclass
class BatchState:
    offset: int = 0
    processed_uids: List[int] = field(default_factory=list)
    last_uid: Optional[int] = None
    is_complete: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "offset": self.offset,
            "processed_uids": self.processed_uids,
            "last_uid": self.last_uid,
            "is_complete": self.is_complete,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "BatchState":
        if not data:
            return cls()
        return cls(
            offset=data.get("offset", 0),
            processed_uids=data.get("processed_uids", []),
            last_uid=data.get("last_uid"),
            is_complete=data.get("is_complete", False),
        )


@dataclass
class BatchResult:
    items: List[Dict[str, Any]]
    state: BatchState
    time_elapsed: float
    time_limit_reached: bool
    total_available: Optional[int] = None

    def to_response(self) -> Dict[str, Any]:
        return {
            "status": "complete" if self.state.is_complete else "partial",
            "items": self.items,
            "items_count": len(self.items),
            "time_elapsed_seconds": round(self.time_elapsed, 2),
            "time_limit_reached": self.time_limit_reached,
            "continuation_state": None
            if self.state.is_complete
            else self.state.to_dict(),
            "total_available": self.total_available,
            "has_more": not self.state.is_complete,
        }


def process_batch_timeboxed(
    items: List[T],
    processor: Callable[[T], Optional[Dict[str, Any]]],
    state: Optional[BatchState] = None,
    time_limit: float = DEFAULT_TIME_LIMIT_SECONDS,
    already_processed: Optional[List[int]] = None,
    uid_extractor: Callable[[T], int] = lambda x: x,  # type: ignore
) -> BatchResult:
    """Process items with a time limit, returning partial results if time runs out.

    Args:
        items: List of items to process
        processor: Function that processes each item, returns dict or None to skip
        state: Previous batch state for continuation
        time_limit: Maximum seconds to process before returning
        already_processed: List of UIDs already processed (to skip duplicates)
        uid_extractor: Function to get UID from item

    Returns:
        BatchResult with processed items and continuation state
    """
    state = state or BatchState()
    already_processed = already_processed or state.processed_uids.copy()
    already_processed_set = set(already_processed)

    results: List[Dict[str, Any]] = []
    start_time = time.time()
    time_limit_reached = False

    items_to_process = items[state.offset :]

    for i, item in enumerate(items_to_process):
        if time.time() - start_time >= time_limit:
            time_limit_reached = True
            state.offset = state.offset + i
            break

        uid = uid_extractor(item)

        if uid in already_processed_set:
            continue

        result = processor(item)
        if result is not None:
            results.append(result)

        state.processed_uids.append(uid)
        already_processed_set.add(uid)
        state.last_uid = uid
    else:
        state.is_complete = True

    elapsed = time.time() - start_time

    return BatchResult(
        items=results,
        state=state,
        time_elapsed=elapsed,
        time_limit_reached=time_limit_reached,
        total_available=len(items),
    )
