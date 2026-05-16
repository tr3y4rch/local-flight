"""Eye-candy widgets for the native first-run setup wizard.

These widgets are intentionally self-contained (they accept the Qt modules
as constructor arguments and do not import Qt at module load time) so they
can ship inside the optional Qt code path without adding hard dependencies
when Qt is unavailable.

Widgets exposed:
    build_stepper         — horizontal animated step indicator
    build_spinner         — rotating glyph spinner with caption
    build_hero            — animated logo + radar-ring background
    build_info_button     — small "ⓘ" helper that pops a rich tooltip
    build_celebration     — full-overlay "✅ Setup complete" finish animation
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable


# ---------------------------------------------------------------------------
# Stepper
# ---------------------------------------------------------------------------

def build_stepper(
    QtCore: Any,
    QtGui: Any,
    QtWidgets: Any,
    *,
    step_names: Iterable[str],
    step_short_labels: Iterable[str],
    on_step_clicked: Callable[[int], None],
    accent_hex: str,
    text_hex: str,
    muted_hex: str,
    line_hex: str,
    compact: bool = False,
) -> Any:
    """Create an animated stepper widget.

    Public API on returned widget:
        widget.set_active(index)
        widget.set_accent(accent_hex, text_hex, muted_hex, line_hex)
    """

    step_names = list(step_names)
    step_short_labels = list(step_short_labels)
    count = len(step_names)

    class _Stepper(QtWidgets.QWidget):
        def __init__(self) -> None:
            super().__init__()
            self._count = count
            self._active = 0
            self._progress = 0.0  # animated 0..count-1
            self._pulse_phase = 0.0
            self._accent = QtGui.QColor(accent_hex)
            self._text = QtGui.QColor(text_hex)
            self._muted = QtGui.QColor(muted_hex)
            self._line = QtGui.QColor(line_hex)
            self._hover_index = -1
            self.setMinimumHeight(62 if not compact else 54)
            self.setMouseTracking(True)
            self.setCursor(QtCore.Qt.PointingHandCursor)
            self._anim = QtCore.QPropertyAnimation(self, b"progress")
            self._anim.setDuration(360)
            self._anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
            self._pulse_timer = QtCore.QTimer(self)
            self._pulse_timer.setInterval(60)
            self._pulse_timer.timeout.connect(self._tick_pulse)
            self._pulse_timer.start()

        def sizeHint(self) -> Any:  # noqa: N802 - Qt naming
            return QtCore.QSize(max(540, self._count * 130), 62 if not compact else 54)

        # animated property used by QPropertyAnimation
        def _get_progress(self) -> float:
            return float(self._progress)

        def _set_progress(self, value: float) -> None:
            self._progress = float(value)
            self.update()

        progress = QtCore.Property(float, _get_progress, _set_progress)

        def set_active(self, index: int) -> None:
            index = max(0, min(int(index), self._count - 1))
            self._active = index
            self._anim.stop()
            self._anim.setStartValue(self._progress)
            self._anim.setEndValue(float(index))
            self._anim.start()

        def set_accent(self, accent_hex: str, text_hex: str, muted_hex: str, line_hex: str) -> None:
            self._accent = QtGui.QColor(accent_hex)
            self._text = QtGui.QColor(text_hex)
            self._muted = QtGui.QColor(muted_hex)
            self._line = QtGui.QColor(line_hex)
            self.update()

        def _tick_pulse(self) -> None:
            self._pulse_phase = (self._pulse_phase + 0.05) % 1.0
            self.update()

        def _centers(self) -> list[float]:
            if self._count <= 1:
                return [self.width() / 2.0]
            pad = 30.0
            usable = max(1.0, self.width() - pad * 2)
            step = usable / (self._count - 1)
            return [pad + step * i for i in range(self._count)]

        def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt naming
            centers = self._centers()
            cy = self._dot_y()
            mx = event.position().x() if hasattr(event, "position") else event.x()
            my = event.position().y() if hasattr(event, "position") else event.y()
            self._hover_index = -1
            for idx, cx in enumerate(centers):
                if (mx - cx) ** 2 + (my - cy) ** 2 <= 18 ** 2:
                    self._hover_index = idx
                    break
            self.update()

        def leaveEvent(self, _event: Any) -> None:  # noqa: N802 - Qt naming
            self._hover_index = -1
            self.update()

        def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt naming
            centers = self._centers()
            cy = self._dot_y()
            mx = event.position().x() if hasattr(event, "position") else event.x()
            my = event.position().y() if hasattr(event, "position") else event.y()
            for idx, cx in enumerate(centers):
                if (mx - cx) ** 2 + (my - cy) ** 2 <= 18 ** 2:
                    on_step_clicked(idx)
                    return

        def _dot_y(self) -> float:
            return 18.0 if not compact else 15.0

        def paintEvent(self, _event: Any) -> None:  # noqa: N802 - Qt naming
            painter = QtGui.QPainter(self)
            try:
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                centers = self._centers()
                cy = self._dot_y()
                radius = 13.0 if not compact else 11.0

                # background line
                line_pen = QtGui.QPen(self._line, 2.0)
                line_pen.setCapStyle(QtCore.Qt.RoundCap)
                painter.setPen(line_pen)
                painter.drawLine(
                    QtCore.QPointF(centers[0], cy),
                    QtCore.QPointF(centers[-1], cy),
                )

                # progress fill line — animated according to self._progress
                if self._count > 1 and self._progress > 0:
                    fill_x = centers[0] + (centers[-1] - centers[0]) * (self._progress / (self._count - 1))
                    fill_pen = QtGui.QPen(self._accent, 3.0)
                    fill_pen.setCapStyle(QtCore.Qt.RoundCap)
                    painter.setPen(fill_pen)
                    painter.drawLine(
                        QtCore.QPointF(centers[0], cy),
                        QtCore.QPointF(fill_x, cy),
                    )

                # nodes
                painter.setPen(QtCore.Qt.NoPen)
                pulse = (math.sin(self._pulse_phase * math.tau) + 1.0) / 2.0
                for idx, cx in enumerate(centers):
                    state = "done" if idx < self._active else "current" if idx == self._active else "pending"

                    # Pulsing outer halo for current step
                    if state == "current":
                        halo = QtGui.QColor(self._accent)
                        halo.setAlpha(int(40 + pulse * 60))
                        painter.setBrush(halo)
                        painter.drawEllipse(
                            QtCore.QPointF(cx, cy),
                            radius + 5 + pulse * 4,
                            radius + 5 + pulse * 4,
                        )

                    # Hover ring
                    if idx == self._hover_index and state != "current":
                        ring = QtGui.QColor(self._accent)
                        ring.setAlpha(60)
                        painter.setBrush(ring)
                        painter.drawEllipse(QtCore.QPointF(cx, cy), radius + 4, radius + 4)

                    # Circle body
                    if state == "done":
                        body = QtGui.QColor(self._accent)
                    elif state == "current":
                        body = QtGui.QColor(self._accent)
                    else:
                        body = QtGui.QColor(self._line)
                    painter.setBrush(body)
                    painter.drawEllipse(QtCore.QPointF(cx, cy), radius, radius)

                    # Number / check
                    glyph_color = QtGui.QColor("#0b0f15") if state in {"done", "current"} else self._muted
                    painter.setPen(glyph_color)
                    font = QtGui.QFont()
                    font.setBold(True)
                    if state == "done":
                        font.setPointSize(11 if not compact else 10)
                        painter.setFont(font)
                        painter.drawText(
                            QtCore.QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                            QtCore.Qt.AlignCenter,
                            "✓",
                        )
                    else:
                        font.setPointSize(10 if not compact else 9)
                        painter.setFont(font)
                        painter.drawText(
                            QtCore.QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                            QtCore.Qt.AlignCenter,
                            str(idx + 1),
                        )
                    painter.setPen(QtCore.Qt.NoPen)

                    # Label below
                    label_text = step_short_labels[idx] if idx < len(step_short_labels) else step_names[idx]
                    label_color = self._text if state in {"done", "current"} else self._muted
                    painter.setPen(label_color)
                    label_font = QtGui.QFont()
                    label_font.setPointSize(9)
                    label_font.setBold(state == "current")
                    painter.setFont(label_font)
                    rect = QtCore.QRectF(cx - 60, cy + radius + 6, 120, 18)
                    painter.drawText(rect, QtCore.Qt.AlignCenter, label_text)
                    painter.setPen(QtCore.Qt.NoPen)
            finally:
                painter.end()

    widget = _Stepper()
    return widget


# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------

def build_spinner(
    QtCore: Any,
    QtGui: Any,
    QtWidgets: Any,
    *,
    accent_hex: str,
    text_hex: str,
) -> Any:
    """Rotating-glyph spinner with caption. show()/hide() and set_text()."""

    class _Spinner(QtWidgets.QFrame):
        GLYPHS = ("◐", "◓", "◑", "◒")  # ◐ ◓ ◑ ◒

        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("SetupSpinner")
            self._idx = 0
            layout = QtWidgets.QHBoxLayout(self)
            layout.setContentsMargins(10, 6, 10, 6)
            layout.setSpacing(8)
            self.glyph = QtWidgets.QLabel(self.GLYPHS[0])
            self.glyph.setStyleSheet(f"color: {accent_hex}; font-size: 16px; font-weight: 900;")
            self.caption = QtWidgets.QLabel("Working…")
            self.caption.setStyleSheet(f"color: {text_hex}; font-size: 12px;")
            layout.addWidget(self.glyph)
            layout.addWidget(self.caption)
            layout.addStretch(1)
            self._timer = QtCore.QTimer(self)
            self._timer.setInterval(160)
            self._timer.timeout.connect(self._tick)
            self.hide()

        def _tick(self) -> None:
            self._idx = (self._idx + 1) % len(self.GLYPHS)
            self.glyph.setText(self.GLYPHS[self._idx])

        def set_text(self, text: str) -> None:
            self.caption.setText(text or "Working…")

        def showEvent(self, event: Any) -> None:  # noqa: N802 - Qt naming
            self._timer.start()
            super().showEvent(event)

        def hideEvent(self, event: Any) -> None:  # noqa: N802 - Qt naming
            self._timer.stop()
            super().hideEvent(event)

    return _Spinner()


# ---------------------------------------------------------------------------
# Hero (welcome page logo + radar ring background)
# ---------------------------------------------------------------------------

def build_hero(
    QtCore: Any,
    QtGui: Any,
    QtWidgets: Any,
    *,
    pixmap: Any,
    accent_hex: str,
    text_hex: str,
    muted_hex: str,
    tagline: str = "Your local airport board, right here on this machine.",
    compact: bool = False,
) -> Any:
    """Build the welcome-page hero block (animated logo + radar rings + tagline)."""

    target_height = 200 if not compact else 168
    logo_size = 132 if not compact else 104

    class _Hero(QtWidgets.QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setMinimumHeight(target_height + 50)
            self._bob = 0.0
            self._ring_phase = 0.0
            self._accent = QtGui.QColor(accent_hex)
            self._text = QtGui.QColor(text_hex)
            self._muted = QtGui.QColor(muted_hex)
            self._pixmap = pixmap
            self._timer = QtCore.QTimer(self)
            self._timer.setInterval(60)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            layout.addSpacing(target_height + 4)
            self.tagline = QtWidgets.QLabel(tagline)
            self.tagline.setAlignment(QtCore.Qt.AlignCenter)
            self.tagline.setStyleSheet(
                f"color: {muted_hex}; font-size: 13px; letter-spacing: 0.02em;"
            )
            layout.addWidget(self.tagline)
            self._opacity = QtWidgets.QGraphicsOpacityEffect(self.tagline)
            self.tagline.setGraphicsEffect(self._opacity)
            self._opacity.setOpacity(0.0)
            self._fade = QtCore.QPropertyAnimation(self._opacity, b"opacity")
            self._fade.setDuration(700)
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.setEasingCurve(QtCore.QEasingCurve.OutCubic)
            QtCore.QTimer.singleShot(220, self._fade.start)

        def _tick(self) -> None:
            self._bob = (self._bob + 0.018) % 1.0
            self._ring_phase = (self._ring_phase + 0.008) % 1.0
            self.update()

        def paintEvent(self, _event: Any) -> None:  # noqa: N802 - Qt naming
            painter = QtGui.QPainter(self)
            try:
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                w = self.width()
                cy = target_height / 2.0 + math.sin(self._bob * math.tau) * 3.0
                cx = w / 2.0

                # Concentric "radar rings" behind the logo
                for ring_idx in range(4):
                    progress = (self._ring_phase + ring_idx * 0.25) % 1.0
                    radius = (logo_size / 2.0) + progress * (logo_size * 0.95)
                    alpha = int(max(0, 80 * (1.0 - progress)))
                    if alpha <= 0:
                        continue
                    ring_color = QtGui.QColor(self._accent)
                    ring_color.setAlpha(alpha)
                    pen = QtGui.QPen(ring_color, 1.4)
                    painter.setPen(pen)
                    painter.setBrush(QtCore.Qt.NoBrush)
                    painter.drawEllipse(QtCore.QPointF(cx, cy), radius, radius)

                # Static halo immediately around the logo
                halo = QtGui.QRadialGradient(QtCore.QPointF(cx, cy), logo_size * 0.9)
                inner = QtGui.QColor(self._accent)
                inner.setAlpha(45)
                outer = QtGui.QColor(self._accent)
                outer.setAlpha(0)
                halo.setColorAt(0.0, inner)
                halo.setColorAt(1.0, outer)
                painter.setBrush(halo)
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(QtCore.QPointF(cx, cy), logo_size * 0.85, logo_size * 0.85)

                # Logo pixmap
                if self._pixmap is not None and not self._pixmap.isNull():
                    rect = QtCore.QRectF(cx - logo_size / 2.0, cy - logo_size / 2.0, logo_size, logo_size)
                    painter.drawPixmap(rect.toRect(), self._pixmap)
                else:
                    # Fallback: brand wordmark
                    font = QtGui.QFont("Audiowide")
                    font.setPointSize(26)
                    painter.setFont(font)
                    painter.setPen(self._text)
                    painter.drawText(
                        QtCore.QRectF(0, cy - 18, w, 36),
                        QtCore.Qt.AlignCenter,
                        "Local Flight",
                    )
            finally:
                painter.end()

    return _Hero()


# ---------------------------------------------------------------------------
# Info bubble (ⓘ helper button)
# ---------------------------------------------------------------------------

def build_info_button(
    QtCore: Any,
    QtGui: Any,
    QtWidgets: Any,
    *,
    text: str,
) -> Any:
    """Small "ⓘ" button. Clicking pops a tooltip with the supplied text."""

    button = QtWidgets.QToolButton()
    button.setObjectName("SetupInfoButton")
    button.setText("ⓘ")  # ⓘ
    button.setCursor(QtCore.Qt.WhatsThisCursor)
    button.setToolTip(text)
    button.setAutoRaise(True)
    button.setFixedSize(22, 22)

    def _show_now() -> None:
        # Show the tooltip immediately at the cursor location.
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), text, button)

    button.clicked.connect(_show_now)
    return button


# ---------------------------------------------------------------------------
# Finish celebration overlay
# ---------------------------------------------------------------------------

def build_celebration(
    QtCore: Any,
    QtGui: Any,
    QtWidgets: Any,
    parent: Any,
    *,
    accent_hex: str,
    text_hex: str,
    bg_hex: str,
) -> Callable[[], None]:
    """Return a function that, when called, shows a brief ✅ celebration overlay.

    The overlay covers ``parent`` and auto-fades out.
    """

    def _fire() -> None:
        try:
            overlay = QtWidgets.QFrame(parent)
            overlay.setObjectName("SetupCelebration")
            overlay.setStyleSheet(
                f"QFrame#SetupCelebration {{ background: {bg_hex}; border-radius: 24px; }}"
            )
            overlay.setGeometry(0, 0, parent.width(), parent.height())
            overlay.raise_()
            layout = QtWidgets.QVBoxLayout(overlay)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addStretch(1)
            mark = QtWidgets.QLabel("✅")
            mark.setAlignment(QtCore.Qt.AlignCenter)
            mark.setStyleSheet("font-size: 96px;")
            layout.addWidget(mark)
            caption = QtWidgets.QLabel("Setup complete — opening Local Flight…")
            caption.setAlignment(QtCore.Qt.AlignCenter)
            caption.setStyleSheet(
                f"color: {text_hex}; font-size: 18px; font-weight: 900; letter-spacing: 0.04em;"
            )
            layout.addWidget(caption)
            layout.addStretch(1)
            opacity = QtWidgets.QGraphicsOpacityEffect(overlay)
            overlay.setGraphicsEffect(opacity)
            opacity.setOpacity(0.0)
            fade_in = QtCore.QPropertyAnimation(opacity, b"opacity", overlay)
            fade_in.setDuration(260)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QtCore.QEasingCurve.OutCubic)
            overlay.show()
            fade_in.start()

            # Keep the overlay around until the host hides it or window goes away.
            overlay._lf_fade_in = fade_in  # type: ignore[attr-defined]
        except Exception:
            pass

    return _fire


# ---------------------------------------------------------------------------
# Page fade helper
# ---------------------------------------------------------------------------

def fade_in_widget(
    QtCore: Any,
    QtWidgets: Any,
    widget: Any,
    *,
    duration_ms: int = 220,
) -> None:
    """Apply a brief fade-in to ``widget``. Safe no-op on failure."""
    try:
        effect = widget.graphicsEffect()
        if not isinstance(effect, QtWidgets.QGraphicsOpacityEffect):
            effect = QtWidgets.QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        anim = QtCore.QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(duration_ms)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        # Keep a reference so GC doesn't kill it mid-animation.
        widget._lf_fade_anim = anim  # type: ignore[attr-defined]
    except Exception:
        pass


__all__ = [
    "build_stepper",
    "build_spinner",
    "build_hero",
    "build_info_button",
    "build_celebration",
    "fade_in_widget",
]
