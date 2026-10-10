from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core.fits_data import FITSData
from ..core.contracts import ResolvedRenderSpec

if TYPE_CHECKING:
    from PySide6.QtGui import QImage


@dataclass(slots=True)
class FrameState:
    """One dataset and the application-owned, disposable products derived from it."""

    data: FITSData
    image: QImage | None = None
    dirty: bool = True
    background: FITSData | None = None
    residual: FITSData | None = None
    preview_dimension: int = 0
    sample_step: int = 1
    resolved_spec: ResolvedRenderSpec | None = None

    def invalidate_render(self) -> None:
        # Keep the old image visible until its replacement is ready.
        self.dirty = True
        self.preview_dimension = 0
        self.resolved_spec = None

    def invalidate_background(self) -> None:
        self.background = None
        self.residual = None


class FrameSession(Sequence[FrameState]):
    """Own a frame sequence atomically, without parallel cache arrays.

    Scientific arrays belong to FITSData; Qt display products stay in this
    application layer. Workers receive dataset snapshots, never this mutable
    session. Request identity remains the responsibility of controllers.
    """

    def __init__(self, frames: Iterable[FITSData] = ()) -> None:
        self._items = [FrameState(data) for data in frames]
        self.current_index = 0

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int | slice) -> FrameState | list[FrameState]:
        return self._items[index]

    def __iter__(self) -> Iterator[FrameState]:
        return iter(self._items)

    @property
    def datasets(self) -> tuple[FITSData, ...]:
        return tuple(frame.data for frame in self._items)

    def append(
        self,
        data: FITSData,
        *,
        image: QImage | None = None,
        preview_dimension: int = 0,
        sample_step: int = 1,
    ) -> FrameState:
        frame = FrameState(
            data=data, image=image, preview_dimension=preview_dimension,
            sample_step=sample_step,
        )
        self._items.append(frame)
        return frame

    def clear(self) -> None:
        self._items.clear()
        self.current_index = 0

    def invalidate_renders(self, indices: Iterable[int] | None = None) -> None:
        for index in range(len(self)) if indices is None else indices:
            self._items[index].invalidate_render()

    def invalidate_backgrounds(self, indices: Iterable[int] | None = None) -> list[int]:
        selected = list(range(len(self))) if indices is None else list(dict.fromkeys(indices))
        selected = [index for index in selected if 0 <= index < len(self)]
        for index in selected:
            self._items[index].invalidate_background()
        return selected
