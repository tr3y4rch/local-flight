"""Reusable visual primitives for the main Qt shell.

These are the shell-side cousins of ``pages/setup_widgets.py`` — same design
language (rounded chips, soft accent fills, rotating-glyph spinner, fading
transitions) but parameterised for the always-on main app instead of the
one-shot setup wizard.

Conventions:
- Every function takes ``QtCore`` / ``QtGui`` / ``QtWidgets`` as parameters
  (no top-level Qt imports) so the module loads cleanly in headless contexts.
- Returned widgets expose plain methods (``set_last_refreshed``, ``set_title``)
  rather than signals, since callers are usually on the main thread already.
"""
from __future__ import annotations

from typing import Any, Iterable

from localflight.native.design import colors_for


# ---------------------------------------------------------------------------
# Pill (rounded status chip)
# ---------------------------------------------------------------------------

def make_pill(QtWidgets: Any, text: str = "", *, tone: str = "muted", icon: str = "") -> Any:
    """Create a rounded status chip styled by ``Pill[tone="…"]`` QSS.

    Tones: ``muted``, ``good``, ``warn``, ``bad``, ``info``.
    """
    label_text = f"{icon}  {text}".strip() if icon else text
    pill = QtWidgets.QLabel(label_text)
    pill.setObjectName("Pill")
    pill.setProperty("tone", tone)
    return pill


def set_pill(pill: Any, text: str, *, tone: str | None = None, icon: str = "") -> None:
    """Update text + optional tone on an existing pill. Repolishes so the
    QSS tone-property restyles immediately."""
    label_text = f"{icon}  {text}".strip() if icon else text
    pill.setText(label_text)
    if tone is not None:
        pill.setProperty("tone", tone)
    try:
        pill.style().unpolish(pill)
        pill.style().polish(pill)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Spinner (rotating-glyph + caption)
# ---------------------------------------------------------------------------

def make_spinner(
    QtCore: Any,
    QtGui: Any,
    QtWidgets: Any,
    *,
    accent_hex: str | None = None,
    text_hex: str | None = None,
    caption: str = "Working…",
) -> Any:
    """Rotating-glyph spinner. Shows/hides via ``show()``/``hide()``;
    update caption via ``set_text(...)``."""
    colors = colors_for()
    accent = accent_hex or colors.get("blue", "#4a9eda")
    text = text_hex or colors.get("text", "#e8f0fe")

    class _Spinner(QtWidgets.QFrame):
        GLYPHS = ("◐", "◓", "◑", "◒")

        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("ShellSpinner")
            self._idx = 0
            layout = QtWidgets.QHBoxLayout(self)
            layout.setContentsMargins(10, 5, 10, 5)
            layout.setSpacing(8)
            self._glyph = QtWidgets.QLabel(self.GLYPHS[0])
            self._glyph.setStyleSheet(f"color: {accent}; font-size: 15px; font-weight: 900;")
            self._caption = QtWidgets.QLabel(caption)
            self._caption.setStyleSheet(f"color: {text}; font-size: 12px;")
            layout.addWidget(self._glyph)
            layout.addWidget(self._caption)
            layout.addStretch(1)
            self._timer = QtCore.QTimer(self)
            self._timer.setInterval(160)
            self._timer.timeout.connect(self._tick)
            self.hide()

        def _tick(self) -> None:
            self._idx = (self._idx + 1) % len(self.GLYPHS)
            self._glyph.setText(self.GLYPHS[self._idx])

        def set_text(self, text: str) -> None:
            self._caption.setText(text or "Working…")

        def showEvent(self, event: Any) -> None:  # noqa: N802 - Qt naming
            self._timer.start()
            super().showEvent(event)

        def hideEvent(self, event: Any) -> None:  # noqa: N802 - Qt naming
            self._timer.stop()
            super().hideEvent(event)

    return _Spinner()


# ---------------------------------------------------------------------------
# Info button (ⓘ helper)
# ---------------------------------------------------------------------------

def make_info_button(QtCore: Any, QtGui: Any, QtWidgets: Any, *, text: str) -> Any:
    """Small "ⓘ" tool button that pops a tooltip with ``text`` on click."""
    button = QtWidgets.QToolButton()
    button.setObjectName("ShellInfoButton")
    button.setText("ⓘ")
    button.setCursor(QtCore.Qt.WhatsThisCursor)
    button.setToolTip(text)
    button.setAccessibleName("Information")
    button.setAccessibleDescription(text)
    button.setAutoRaise(True)
    button.setFixedSize(22, 22)
    try:
        button.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
    except Exception:
        button.setFocusPolicy(QtCore.Qt.StrongFocus)

    def _show_now(*, at_cursor: bool = True) -> None:
        try:
            position = QtGui.QCursor.pos() if at_cursor else button.mapToGlobal(button.rect().bottomLeft())
            QtWidgets.QToolTip.showText(position, text, button)
        except Exception:
            pass

    class _InfoButtonEventFilter(QtCore.QObject):
        def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - Qt naming
            try:
                event_type = getattr(getattr(QtCore.QEvent, "Type", QtCore.QEvent), "KeyPress")
                key_enum = getattr(QtCore.Qt, "Key", QtCore.Qt)
                keys = {
                    getattr(key_enum, "Key_Return"),
                    getattr(key_enum, "Key_Enter"),
                    getattr(key_enum, "Key_Space"),
                }
                if watched is button and event.type() == event_type and event.key() in keys:
                    _show_now(at_cursor=False)
                    event.accept()
                    return True
            except Exception:
                pass
            return super().eventFilter(watched, event)

    button._localflight_info_filter = _InfoButtonEventFilter(button)  # type: ignore[attr-defined]
    button.installEventFilter(button._localflight_info_filter)
    button.clicked.connect(lambda: _show_now(at_cursor=True))
    return button


# ---------------------------------------------------------------------------
# Page hero (unified per-page header band)
# ---------------------------------------------------------------------------

def make_page_hero(
    QtCore: Any,
    QtGui: Any,
    QtWidgets: Any,
    *,
    emoji: str = "",
    title: str = "",
    subtitle: str = "",
    info_text: str = "",
    actions: Iterable[Any] = (),
    show_last_refreshed: bool = True,
) -> Any:
    """Build a consistent page header band.

    Returns a QFrame with helpers:
        hero.set_title(text)
        hero.set_subtitle(text)
        hero.set_last_refreshed(text)        # e.g. "Updated 14:32:08"
        hero.set_status(text, tone)          # tone: good/warn/bad/muted/info
        hero.add_action(button)              # append more action buttons later
    """

    class _Hero(QtWidgets.QFrame):
        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("PageHero")
            outer = QtWidgets.QHBoxLayout(self)
            outer.setContentsMargins(16, 12, 16, 12)
            outer.setSpacing(14)

            # Left: emoji + title/subtitle column
            text_col = QtWidgets.QVBoxLayout()
            text_col.setSpacing(2)
            head_row = QtWidgets.QHBoxLayout()
            head_row.setSpacing(8)
            self._emoji = QtWidgets.QLabel(emoji)
            self._emoji.setObjectName("PageHeroEmoji")
            self._title = QtWidgets.QLabel(title)
            self._title.setObjectName("PageHeroTitle")
            head_row.addWidget(self._emoji)
            head_row.addWidget(self._title)
            if info_text:
                head_row.addWidget(make_info_button(QtCore, QtGui, QtWidgets, text=info_text))
            head_row.addStretch(1)
            text_col.addLayout(head_row)
            self._subtitle = QtWidgets.QLabel(subtitle)
            self._subtitle.setObjectName("PageHeroSubtitle")
            self._subtitle.setWordWrap(True)
            text_col.addWidget(self._subtitle)
            outer.addLayout(text_col, 1)

            # Right: action area
            self._action_row = QtWidgets.QHBoxLayout()
            self._action_row.setSpacing(8)
            self._action_row.addStretch(1)
            for btn in actions:
                self._action_row.addWidget(btn)
            outer.addLayout(self._action_row, 0)

            # Far right: status pill + last-refreshed pill
            self._status_pill = make_pill(QtWidgets, "", tone="muted")
            self._status_pill.setVisible(False)
            outer.addWidget(self._status_pill)
            if show_last_refreshed:
                self._last_refreshed = make_pill(QtWidgets, "Not loaded yet", tone="muted", icon="⏱️")
                outer.addWidget(self._last_refreshed)
            else:
                self._last_refreshed = None

        # ----- helpers
        def set_title(self, text: str) -> None:
            self._title.setText(text)

        def set_subtitle(self, text: str) -> None:
            self._subtitle.setText(text)

        def set_last_refreshed(self, text: str) -> None:
            if self._last_refreshed is not None:
                set_pill(self._last_refreshed, text, icon="⏱️")

        def set_status(self, text: str, tone: str = "muted") -> None:
            if not text:
                self._status_pill.setVisible(False)
                return
            set_pill(self._status_pill, text, tone=tone)
            self._status_pill.setVisible(True)

        def add_action(self, button: Any) -> None:
            self._action_row.addWidget(button)

    return _Hero()


# ---------------------------------------------------------------------------
# Toast notification
# ---------------------------------------------------------------------------

def show_toast(
    QtCore: Any,
    QtGui: Any,
    QtWidgets: Any,
    parent: Any,
    *,
    text: str,
    tone: str = "info",
    duration_ms: int = 2400,
) -> Any:
    """Slide-in transient toast in the bottom-right of ``parent``.

    Tones map to existing Pill tones for color: good/warn/bad/info/muted.
    The toast auto-fades and removes itself.
    """
    if parent is None or not text:
        return None
    try:
        host = parent.window() if hasattr(parent, "window") else parent
    except Exception:
        host = parent

    toast = QtWidgets.QFrame(host)
    toast.setObjectName("ShellToast")
    toast.setProperty("tone", tone)
    layout = QtWidgets.QHBoxLayout(toast)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(8)
    icon_for = {"good": "✅", "warn": "⚠️", "bad": "⛔", "info": "ℹ️"}
    icon_label = QtWidgets.QLabel(icon_for.get(tone, "ℹ️"))
    icon_label.setObjectName("ShellToastIcon")
    text_label = QtWidgets.QLabel(text)
    text_label.setObjectName("ShellToastText")
    text_label.setWordWrap(True)
    text_label.setMaximumWidth(360)
    layout.addWidget(icon_label)
    layout.addWidget(text_label)
    toast.adjustSize()

    # Position in bottom-right of the host.
    try:
        host_w = host.width()
        host_h = host.height()
        margin = 18
        toast.move(
            max(margin, host_w - toast.width() - margin),
            max(margin, host_h - toast.height() - margin - 20),
        )
    except Exception:
        toast.move(20, 20)

    opacity = QtWidgets.QGraphicsOpacityEffect(toast)
    toast.setGraphicsEffect(opacity)
    opacity.setOpacity(0.0)

    fade_in = QtCore.QPropertyAnimation(opacity, b"opacity", toast)
    fade_in.setDuration(220)
    fade_in.setStartValue(0.0)
    fade_in.setEndValue(1.0)
    fade_in.setEasingCurve(QtCore.QEasingCurve.OutCubic)
    fade_out = QtCore.QPropertyAnimation(opacity, b"opacity", toast)
    fade_out.setDuration(320)
    fade_out.setStartValue(1.0)
    fade_out.setEndValue(0.0)
    fade_out.setEasingCurve(QtCore.QEasingCurve.InCubic)
    fade_out.finished.connect(toast.deleteLater)

    toast.show()
    toast.raise_()
    fade_in.start()
    QtCore.QTimer.singleShot(max(800, int(duration_ms)), fade_out.start)
    toast._lf_fade_in = fade_in  # type: ignore[attr-defined]
    toast._lf_fade_out = fade_out  # type: ignore[attr-defined]
    return toast


# ---------------------------------------------------------------------------
# Page-switch fade
# ---------------------------------------------------------------------------

def fade_swap(
    QtCore: Any,
    QtWidgets: Any,
    stack: Any,
    index: int,
    *,
    duration_ms: int = 180,
) -> None:
    """Fade-out the current page, switch to ``index``, fade-in the new page.

    Falls back to an instant switch if anything errors so navigation is
    never blocked by chrome.
    """
    try:
        if not hasattr(stack, "setCurrentIndex"):
            return
        current = stack.currentWidget()
        if current is None or index < 0 or index >= stack.count():
            stack.setCurrentIndex(max(0, min(index, stack.count() - 1)))
            return
        if index == stack.currentIndex():
            return  # nothing to do

        def _swap() -> None:
            stack.setCurrentIndex(index)
            new_page = stack.currentWidget()
            if new_page is None:
                return
            effect_in = new_page.graphicsEffect()
            if not isinstance(effect_in, QtWidgets.QGraphicsOpacityEffect):
                effect_in = QtWidgets.QGraphicsOpacityEffect(new_page)
                new_page.setGraphicsEffect(effect_in)
            effect_in.setOpacity(0.0)
            anim_in = QtCore.QPropertyAnimation(effect_in, b"opacity", new_page)
            anim_in.setDuration(duration_ms)
            anim_in.setStartValue(0.0)
            anim_in.setEndValue(1.0)
            anim_in.setEasingCurve(QtCore.QEasingCurve.OutCubic)
            anim_in.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
            new_page._lf_fade_in = anim_in  # type: ignore[attr-defined]

        effect_out = current.graphicsEffect()
        if not isinstance(effect_out, QtWidgets.QGraphicsOpacityEffect):
            effect_out = QtWidgets.QGraphicsOpacityEffect(current)
            current.setGraphicsEffect(effect_out)
        effect_out.setOpacity(1.0)
        anim_out = QtCore.QPropertyAnimation(effect_out, b"opacity", current)
        anim_out.setDuration(max(80, duration_ms // 2))
        anim_out.setStartValue(1.0)
        anim_out.setEndValue(0.0)
        anim_out.setEasingCurve(QtCore.QEasingCurve.InCubic)
        anim_out.finished.connect(_swap)
        anim_out.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        current._lf_fade_out = anim_out  # type: ignore[attr-defined]
    except Exception:
        try:
            stack.setCurrentIndex(max(0, min(index, stack.count() - 1)))
        except Exception:
            pass


__all__ = [
    "make_pill",
    "set_pill",
    "make_spinner",
    "make_info_button",
    "make_page_hero",
    "show_toast",
    "fade_swap",
]
