"""FlowGrid — a QWidget wrapping QGridLayout that re-columns on resize.

Performance contract
--------------------
add_widget()  is O(1)  — inserts directly at the next grid slot, no teardown.
resizeEvent() is O(n)  — only fires when the visible column count changes.

Never call _relayout inside add_widget.  The layout is only rebuilt when the
window changes width enough to change the column count.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)


class FlowGrid(QWidget):
    """Responsive grid that re-flows its children when the available width changes."""

    def __init__(
        self,
        item_width: int,
        spacing: int = 8,
        margins: tuple[int, int, int, int] = (24, 24, 24, 24),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._item_width  = item_width
        self._spacing     = spacing
        self._items:       list[QWidget] = []
        self._current_cols = 0

        self._layout = QGridLayout(self)
        self._layout.setSpacing(spacing)
        self._layout.setContentsMargins(*margins)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    # ── public API ────────────────────────────────────────────────────

    def add_widget(self, widget: QWidget) -> None:
        """Append widget in O(1) — directly inserts at the next grid slot."""
        self._items.append(widget)

        # Resolve columns on first add (widget may not have a size yet).
        # If width is still 0, default to 1 column; resizeEvent corrects it.
        if self._current_cols == 0:
            self._current_cols = max(1, self._cols_for_width())

        idx = len(self._items) - 1
        row, col = divmod(idx, self._current_cols)
        self._layout.addWidget(widget, row, col)

    def clear(self) -> None:
        """Remove all widgets and schedule them for deletion."""
        while self._layout.count():
            self._layout.takeAt(0)
        for w in self._items:
            w.deleteLater()
        self._items.clear()
        self._current_cols = 0

    # ── Qt overrides ──────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Only rebuild when column count actually changes — O(n) but rare.
        self._relayout(force=False)

    # ── internal ──────────────────────────────────────────────────────

    def _cols_for_width(self) -> int:
        m = self._layout.contentsMargins()
        usable = self.width() - m.left() - m.right()
        return max(1, usable // (self._item_width + self._spacing))

    def _relayout(self, force: bool = False) -> None:
        """Full teardown + rebuild.  Called only on column-count change."""
        cols = self._cols_for_width()
        if cols == self._current_cols and not force:
            return
        self._current_cols = cols

        while self._layout.count():
            self._layout.takeAt(0)

        for i, widget in enumerate(self._items):
            row, col = divmod(i, cols)
            self._layout.addWidget(widget, row, col)


# ── PaginatedGrid ─────────────────────────────────────────────────────

class PaginatedGrid(QWidget):
    """Fixed-row paginated grid.

    Shows exactly `rows` rows of cards; columns fill the available width.
    Only the current page's widgets are alive — previous/next pages are
    created on demand so memory stays flat.

    Usage:
        grid = PaginatedGrid(item_width=190, rows=3)
        grid.set_data(my_list, factory_fn)

    factory_fn(item) -> QWidget   called once per visible card per page.
    """

    def __init__(
        self,
        item_width: int,
        rows: int = 3,
        spacing: int = 8,
        margins: tuple[int, int, int, int] = (0, 16, 0, 0),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._item_width = item_width
        self._rows       = rows
        self._spacing    = spacing
        self._margins    = margins
        self._data:    list[Any] = []
        self._factory: Callable[[Any], QWidget] | None = None
        self._page     = 0
        self._cols     = 0

        from src.music_player.ui.glyphs import CHEVRON_LEFT, CHEVRON_RIGHT, MDL2_FONT

        _BTN = 42   # 1.5× original 28 px

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Nav row ABOVE the grid, floated to the right so it sits above the
        # far-right column.  Buttons are 1.5× larger; the page label bridges
        # a gap of 3× button width between the two chevrons.
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, margins[2], 4)
        nav.setSpacing(0)
        nav.addStretch()

        _btn_style = (
            "QPushButton{background:transparent;color:#555;border:none;}"
            "QPushButton:hover{color:#fff;}"
            "QPushButton:disabled{color:#2a2a2e;}"
        )

        self._prev_btn = QPushButton(CHEVRON_LEFT)
        self._prev_btn.setFont(QFont(MDL2_FONT, 16))
        self._prev_btn.setFixedSize(_BTN, _BTN)
        self._prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_btn.setStyleSheet(_btn_style)
        self._prev_btn.clicked.connect(self._go_prev)

        self._page_lbl = QLabel("")
        self._page_lbl.setFixedWidth(_BTN * 3)   # 3× gap between chevrons
        self._page_lbl.setStyleSheet("color:#555; font-size:13px; background:transparent;")
        self._page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._next_btn = QPushButton(CHEVRON_RIGHT)
        self._next_btn.setFont(QFont(MDL2_FONT, 16))
        self._next_btn.setFixedSize(_BTN, _BTN)
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setStyleSheet(_btn_style)
        self._next_btn.clicked.connect(self._go_next)

        nav.addWidget(self._prev_btn)
        nav.addWidget(self._page_lbl)
        nav.addWidget(self._next_btn)
        root.addLayout(nav)

        # Grid area below the nav
        self._grid_host = QWidget()
        self._grid_host.setStyleSheet("background:transparent;")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setSpacing(spacing)
        self._grid.setContentsMargins(*margins)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        root.addWidget(self._grid_host)

    # ── public ────────────────────────────────────────────────────────

    def set_data(self, data: list[Any], factory: Callable[[Any], QWidget]) -> None:
        self._data    = data
        self._factory = factory
        self._page    = 0
        cols = self._cols_for_width()
        self._cols = max(1, cols)
        self._render()

    # ── Qt overrides ──────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        new_cols = max(1, self._cols_for_width())
        if new_cols != self._cols and self._factory:
            # Keep the first visible item's index, recompute page
            first = self._page * (self._cols * self._rows)
            self._cols = new_cols
            self._page = first // max(1, self._cols * self._rows)
            self._render()

    # ── internal ──────────────────────────────────────────────────────

    def _cols_for_width(self) -> int:
        ml, mt, mr, mb = self._margins
        usable = self.width() - ml - mr
        return max(1, usable // (self._item_width + self._spacing))

    def _items_per_page(self) -> int:
        return max(1, self._cols * self._rows)

    def _total_pages(self) -> int:
        if not self._data:
            return 1
        return max(1, math.ceil(len(self._data) / self._items_per_page()))

    def _render(self) -> None:
        # Destroy current page widgets
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._factory or not self._data:
            self._update_nav()
            return

        ipp   = self._items_per_page()
        start = self._page * ipp
        end   = min(start + ipp, len(self._data))

        for i, datum in enumerate(self._data[start:end]):
            widget = self._factory(datum)
            row, col = divmod(i, self._cols)
            self._grid.addWidget(widget, row, col)

        self._update_nav()

    def _update_nav(self) -> None:
        total = self._total_pages()
        self._page_lbl.setText(f"{self._page + 1} / {total}")
        self._prev_btn.setEnabled(self._page > 0)
        self._next_btn.setEnabled(self._page < total - 1)
        # Hide nav entirely if everything fits on one page
        self._prev_btn.setVisible(total > 1)
        self._next_btn.setVisible(total > 1)
        self._page_lbl.setVisible(total > 1)

    def _go_prev(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._render()

    def _go_next(self) -> None:
        if self._page < self._total_pages() - 1:
            self._page += 1
            self._render()
