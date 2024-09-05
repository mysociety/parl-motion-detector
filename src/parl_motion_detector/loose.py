from dataclasses import dataclass
from typing import Generic, Iterator, Optional, TypeVar

T = TypeVar("T")


@dataclass
class PeakAheadResult(Generic[T]):
    prev_item: Optional[T]
    current_item: T
    next_item: Optional[T]


def peak_ahead_iterator(iterable: Iterator[T]) -> Iterator[PeakAheadResult[T]]:
    prev_item = None
    current_item = next(iterable)
    next_item = next(iterable, None)
    while current_item:
        yield PeakAheadResult(prev_item, current_item, next_item)
        prev_item = current_item
        current_item = next_item
        next_item = next(iterable, None)
