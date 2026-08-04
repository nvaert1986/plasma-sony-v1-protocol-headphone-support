"""PyQt6 GUI.

Layout:
* a header row with a device dropdown + Rescan button + status,
* a top-level tab per detected headset (kept in sync with the dropdown),
* per headset, feature sub-tabs (Info, Noise & Ambient, Battery, + placeholders).

Feature sub-tabs are added generously now; ones without a verified command are
shown disabled ("coming soon") so the shape of the app is visible from day one.
"""

from __future__ import annotations

import logging
import os
from typing import ClassVar

from PyQt6.QtCore import Qt, QThreadPool, QTimer
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSlider,
    QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
)

from . import __version__
from .device import DeviceState
from .enums_ui import ASM_MAX
from .workers import DeviceConnection, ScanWorker

log = logging.getLogger(__name__)


def _resource(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), "resources", name)


def _mark_pending(pending: set, *widgets) -> None:
    """Start an in-flight write: remember these widgets and disable them until
    the device confirms. While pending, a background state refresh (the 30 s
    poll) must not repaint them — otherwise a snapshot taken before the click
    lands afterwards and visibly undoes it (the A->B->A flicker). This mirrors
    Sony's own single-control update model; the confirmation arrives as
    ``settingApplied`` and clears the pending set."""
    pending.update(widgets)
    for w in widgets:
        w.setEnabled(False)


def _set_row_visible(form: QFormLayout, field: QWidget, visible: bool) -> None:
    """Hide a QFormLayout row (field + its label) — for per-control gating of
    features the connected model doesn't support."""
    field.setVisible(visible)
    label = form.labelForField(field)
    if label is not None:
        label.setVisible(visible)


# Model name (substring) -> product image under resources/. Order matters:
# more specific names first (so "WH-1000XM4" wins before a looser match).
MODEL_IMAGES = {
    "WH-1000XM4": "wh1000xm4.png",
    "WH-1000XM3": "wh1000xm3.png",
    "MDR-1000X": "mdr1000x.png",
}


def app_icon() -> QIcon:
    """Prefer the desktop's headphone icon; fall back to a drawn one."""
    themed = QIcon.fromTheme("audio-headphones")
    if not themed.isNull():
        return themed
    themed = QIcon.fromTheme("audio-headset")
    if not themed.isNull():
        return themed
    # fallback: draw a simple headphone glyph (not the old blue tile)
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    accent = QColor("#3b82f6")
    pen = QPen(accent)
    pen.setWidth(6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(14, 12, 36, 34, 0, 180 * 16)      # headband
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(accent)
    p.drawRoundedRect(12, 30, 12, 22, 4, 4)      # left cup
    p.drawRoundedRect(40, 30, 12, 22, 4, 4)      # right cup
    p.end()
    return QIcon(pix)


# ---------------------------------------------------------------------------
# Feature sub-panels
# ---------------------------------------------------------------------------

class InfoPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        form = QFormLayout(self)
        self._model = QLabel("—")
        self._model_id = QLabel("—")
        self._serial = QLabel("—")
        self._device_id = QLabel("—")
        self._version = QLabel("—")
        self._codes = QLabel("—")
        self._proto = QLabel("—")
        self._codec = QLabel("—")
        self._dsee = QLabel("—")
        self._battery = QLabel("—")
        for w in (self._serial, self._device_id, self._codes):
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Model:", self._model)
        form.addRow("Model ID:", self._model_id)
        form.addRow("Serial number:", self._serial)
        form.addRow("Device ID:", self._device_id)
        form.addRow("Battery:", self._battery)
        form.addRow("Codec:", self._codec)
        form.addRow("DSEE Extreme:", self._dsee)
        form.addRow("Version fields:", self._version)
        form.addRow("Codes:", self._codes)
        form.addRow("Protocol info:", self._proto)

    def update_state(self, st: DeviceState, confirmed: bool = False) -> None:
        self._model.setText(st.model_name or "—")
        self._model_id.setText(st.model_id or "—")
        self._serial.setText(st.serial or "—")
        self._device_id.setText(st.device_id or "—")
        self._version.setText(".".join(str(v) for v in st.version_fields) or "—")
        codes = {k: v for k, v in st.identifiers.items() if k in (0x02, 0x04)}
        self._codes.setText(", ".join(f"{v}" for v in codes.values()) or "—")
        self._proto.setText(st.protocol_raw.hex(" ") or "—")
        self._codec.setText(st.codec or "—")
        self._dsee.setText("—" if st.dsee is None else ("Auto" if st.dsee else "Off"))
        b = st.battery
        self._battery.setText(f"{b.level}%{' (charging)' if b.charging else ''}"
                              if b is not None else "—")


class BatteryPanel(QWidget):
    def __init__(self, connection: DeviceConnection) -> None:
        super().__init__()
        self._conn = connection
        self._loading = False
        self._pending: set = set()
        lay = QVBoxLayout(self)
        box = QGroupBox("Battery")
        inner = QVBoxLayout(box)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._label = QLabel("Unknown")
        inner.addWidget(self._bar)
        inner.addWidget(self._label)
        lay.addWidget(box)

        # Auto Power Off is capability-driven: the model advertises which options
        # it supports (XM4: when-removed/never; XM3: 5/30/60/180 min/never).
        self._pbox = QGroupBox("Auto power off")
        pinner = QFormLayout(self._pbox)
        self._apo = QComboBox()
        self._apo.activated.connect(self._apply_apo)
        pinner.addRow("Turn off:", self._apo)
        self._pbox.setVisible(False)   # shown only if the model supports it
        lay.addWidget(self._pbox)
        lay.addStretch(1)

    def _apply_apo(self, index: int) -> None:
        if self._loading:
            return
        element = self._apo.itemData(index)
        if element is not None:
            self._conn.set_auto_power_off(int(element))
            _mark_pending(self._pending, self._apo)

    def clear_inflight(self) -> None:
        self._pending.clear()
        self._apo.setEnabled(True)

    def update_state(self, st: DeviceState, confirmed: bool = False) -> None:
        b = st.battery
        if b is None:
            self._label.setText("Unknown")
        else:
            self._bar.setValue(int(b.level))
            charge = " (charging)" if b.charging else ""
            if b.left is not None:
                self._label.setText(f"L {b.left}%  R {b.right}%{charge}")
            else:
                self._label.setText(f"{b.level}%{charge}")
        self._pbox.setVisible(bool(st.apo_options))
        if confirmed:
            self.clear_inflight()
        if st.apo_options and self._apo not in self._pending:
            from .protocol.messages import APO_ELEMENT_LABELS
            self._loading = True
            try:
                # rebuild the option list if it changed
                current_ids = [self._apo.itemData(i) for i in range(self._apo.count())]
                if current_ids != st.apo_options:
                    self._apo.clear()
                    for el in st.apo_options:
                        self._apo.addItem(APO_ELEMENT_LABELS.get(el, f"Option {el:#04x}"), el)
                if st.apo_current is not None:
                    idx = self._apo.findData(st.apo_current)
                    if idx >= 0:
                        self._apo.setCurrentIndex(idx)
            finally:
                self._loading = False


class NoiseAmbientPanel(QWidget):
    """Noise-cancelling / ambient-sound control (legacy v1 NC/ASM path)."""

    def __init__(self, connection: DeviceConnection) -> None:
        super().__init__()
        self._conn = connection
        self._loading = False
        self._pending: set = set()

        lay = QVBoxLayout(self)
        box = QGroupBox("Sound control")
        form = QFormLayout(box)

        self._ambient = QCheckBox("Ambient sound (off = noise cancelling)")
        self._ambient.toggled.connect(self._apply)

        self._level = QSlider(Qt.Orientation.Horizontal)
        # Ambient level starts at 1: on these devices level 0 is the noise-
        # cancelling end of the scale, not a valid ambient setting (the headset
        # pulls a sent 0 up to 1), and Sony's own app numbers ambient from 1.
        self._level.setRange(1, ASM_MAX)
        self._level.setPageStep(1)
        self._level.sliderReleased.connect(self._apply)

        self._voice = QCheckBox("Focus on voice")
        self._voice.toggled.connect(self._apply)

        form.addRow(self._ambient)
        form.addRow("Ambient level:", self._level)
        form.addRow(self._voice)

        lay.addWidget(box)
        note = QLabel("Uses the verified v1 NC/ASM command. Values sync back from "
                      "the headset after each change.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        lay.addWidget(note)
        lay.addStretch(1)

    def _apply(self, *_: object) -> None:
        if self._loading:
            return
        ambient = self._ambient.isChecked()
        self._conn.set_ncasm(ambient, self._voice.isChecked(), self._level.value())
        # All three fields go in one NC/ASM write — hold them until it confirms.
        _mark_pending(self._pending, self._ambient, self._level, self._voice)

    def clear_inflight(self) -> None:
        self._pending.clear()
        for w in (self._ambient, self._level, self._voice):
            w.setEnabled(True)

    def update_state(self, st: DeviceState, confirmed: bool = False) -> None:
        n = st.ncasm
        if n is None:
            return
        if confirmed:
            self._pending.clear()
        self._loading = True
        try:
            if self._ambient not in self._pending:
                self._ambient.setChecked(n.enabled)
                self._ambient.setEnabled(True)
            if self._level not in self._pending:
                self._level.setValue(int(n.asm_level))
                self._level.setEnabled(n.enabled)
            if self._voice not in self._pending:
                self._voice.setChecked(n.focus_on_voice)
                self._voice.setEnabled(n.enabled)
        finally:
            self._loading = False


class EqualizerPanel(QWidget):
    """5-band + Clear Bass equalizer (XM4). Bands are -10..+10.

    On some models the graphic EQ is mutually exclusive with LDAC (see protocol
    doc §7.3.1): engaging it drops the A2DP link to SBC. For those models we gate
    the whole panel while the active codec is LDAC and tell the user to switch to
    a stable-connection (SBC) mode first.
    """

    # Models where applying an EQ change while on LDAC forces the codec to SBC.
    _EQ_LDAC_INCOMPATIBLE: ClassVar[set[str]] = {"WH-1000XM3"}

    def __init__(self, connection: DeviceConnection) -> None:
        super().__init__()
        self._conn = connection
        self._loading = False
        self._pending: set = set()

        from .protocol.messages import (
            EQ_BAND_LABELS, EQ_BAND_MAX, EQ_BAND_MIN, EQ_PRESETS,
        )

        lay = QVBoxLayout(self)

        # preset selector
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Preset:"))
        self._preset = QComboBox()
        for pid, name in EQ_PRESETS:
            self._preset.addItem(name, pid)
        self._preset.activated.connect(self._on_preset)
        prow.addWidget(self._preset, 1)
        lay.addLayout(prow)

        box = QGroupBox("Bands")
        grid = QHBoxLayout(box)
        self._sliders: list[QSlider] = []
        for label in EQ_BAND_LABELS:
            col = QVBoxLayout()
            s = QSlider(Qt.Orientation.Vertical)
            s.setRange(EQ_BAND_MIN, EQ_BAND_MAX)
            s.setValue(0)
            s.setMinimumHeight(120)
            s.setTickPosition(QSlider.TickPosition.TicksBothSides)
            s.setTickInterval(5)
            s.sliderReleased.connect(self._apply_bands)
            self._sliders.append(s)
            col.addWidget(s, 1, Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(QLabel(label), 0, Qt.AlignmentFlag.AlignHCenter)
            grid.addLayout(col)
        lay.addWidget(box)

        self._note = QLabel("Pick a preset, or select a Custom slot to edit the "
                            "bands. Named presets are read-only.")
        self._note.setWordWrap(True)
        self._note.setStyleSheet("color: gray;")
        lay.addWidget(self._note)

    def _on_preset(self, index: int) -> None:
        if self._loading:
            return
        self._conn.set_eq_preset(int(self._preset.itemData(index)))
        _mark_pending(self._pending, self._preset, *self._sliders)

    def _apply_bands(self) -> None:
        if self._loading:
            return
        self._conn.set_eq_bands([s.value() for s in self._sliders])
        _mark_pending(self._pending, self._preset, *self._sliders)

    def clear_inflight(self) -> None:
        self._pending.clear()
        self._preset.setEnabled(True)
        for s in self._sliders:
            s.setEnabled(True)

    def update_state(self, st: DeviceState, confirmed: bool = False) -> None:
        eq = st.eq
        if eq is None:
            return
        from .protocol.messages import EQ_CUSTOM_PRESETS

        if confirmed:
            self._pending.clear()
        # While a write is in flight, don't let a background refresh repaint the
        # EQ (it would flicker the sliders back to the pre-write curve).
        if self._preset in self._pending or any(s in self._pending
                                                for s in self._sliders):
            return

        # Gate: on affected models, LDAC and the EQ can't coexist.
        ldac_locked = (st.model_name in self._EQ_LDAC_INCOMPATIBLE
                       and st.codec == "LDAC")
        editable = (not ldac_locked) and eq.preset_id in EQ_CUSTOM_PRESETS

        self._loading = True
        try:
            # strict=False: tolerate a band-count mismatch (fixed 6 sliders vs
            # whatever the device reports) rather than raising in the UI callback.
            for s, v in zip(self._sliders, eq.bands, strict=False):
                s.setValue(int(v))
            for s in self._sliders:
                # sliders are only editable in a Custom/User preset (and never
                # while LDAC-locked)
                s.setEnabled(editable)
            self._preset.setEnabled(not ldac_locked)
            idx = self._preset.findData(eq.preset_id)
            if idx >= 0:
                self._preset.setCurrentIndex(idx)
        finally:
            self._loading = False

        if ldac_locked:
            self._note.setText(
                "The equalizer is only supported in SBC mode on this model. "
                "It is disabled while LDAC is active — set Sound Quality to "
                "“Prioritize Stable Connection” (Connectivity tab) to "
                "use it.")
        else:
            self._note.setText(
                "Drag a band and release to set your custom curve."
                if editable else
                "This preset's bands are fixed. Choose a Custom slot to edit them.")


class DseePanel(QWidget):
    """DSEE Extreme — Off / Auto (the only two options on the XM4)."""

    def __init__(self, connection: DeviceConnection) -> None:
        super().__init__()
        self._conn = connection
        self._loading = False
        self._pending: set = set()
        lay = QVBoxLayout(self)
        box = QGroupBox("DSEE Extreme")
        inner = QVBoxLayout(box)
        self._enabled = QCheckBox("Enable DSEE Extreme (Auto)")
        self._enabled.toggled.connect(self._apply)
        inner.addWidget(self._enabled)
        lay.addWidget(box)
        note = QLabel("Upscales compressed audio. The XM4 offers only Auto or Off; "
                      "it may be unavailable while an equalizer preset is active.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        lay.addWidget(note)
        lay.addStretch(1)

    def _apply(self, *_: object) -> None:
        if self._loading:
            return
        self._conn.set_dsee(self._enabled.isChecked())
        _mark_pending(self._pending, self._enabled)

    def clear_inflight(self) -> None:
        self._pending.clear()
        self._enabled.setEnabled(True)

    def update_state(self, st: DeviceState, confirmed: bool = False) -> None:
        if st.dsee is None:
            return
        if confirmed:
            self._pending.clear()
        if self._enabled in self._pending:
            return
        self._loading = True
        try:
            self._enabled.setChecked(bool(st.dsee))
            self._enabled.setEnabled(True)
        finally:
            self._loading = False


class SpeakToChatPanel(QWidget):
    def __init__(self, connection: DeviceConnection) -> None:
        super().__init__()
        self._conn = connection
        self._loading = False
        self._pending: set = set()
        from .protocol.messages import STC_SENSITIVITY, STC_TIMEOUT

        lay = QVBoxLayout(self)
        box = QGroupBox("Speak-to-Chat")
        form = QFormLayout(box)
        self._enabled = QCheckBox("Enable Speak-to-Chat")
        self._enabled.toggled.connect(self._apply)
        self._sens = QComboBox()
        for val, name in STC_SENSITIVITY:
            self._sens.addItem(name, val)
        self._sens.activated.connect(self._apply)
        self._time = QComboBox()
        for val, name in STC_TIMEOUT:
            self._time.addItem(name, val)
        self._time.activated.connect(self._apply)
        form.addRow(self._enabled)
        form.addRow("Voice detect sensitivity:", self._sens)
        form.addRow("Time until mode closes:", self._time)
        lay.addWidget(box)
        lay.addStretch(1)

    def _apply(self, *_: object) -> None:
        if self._loading:
            return
        enabled = self._enabled.isChecked()
        self._conn.set_stc(enabled,
                           int(self._sens.currentData()),
                           int(self._time.currentData()))
        _mark_pending(self._pending, self._enabled, self._sens, self._time)

    def clear_inflight(self) -> None:
        self._pending.clear()
        for w in (self._enabled, self._sens, self._time):
            w.setEnabled(True)

    def update_state(self, st: DeviceState, confirmed: bool = False) -> None:
        stc = st.stc
        if stc is None:
            return
        if confirmed:
            self._pending.clear()
        if any(w in self._pending for w in (self._enabled, self._sens, self._time)):
            return
        self._loading = True
        try:
            self._enabled.setChecked(stc.enabled)
            self._enabled.setEnabled(True)
            si = self._sens.findData(stc.sensitivity)
            if si >= 0:
                self._sens.setCurrentIndex(si)
            ti = self._time.findData(stc.timeout)
            if ti >= 0:
                self._time.setCurrentIndex(ti)
            self._sens.setEnabled(stc.enabled)
            self._time.setEnabled(stc.enabled)
        finally:
            self._loading = False


def _confirm_reboot(parent, feature: str, extra: str = "") -> bool:
    """Warn that a change reboots/reconnects the headphones. Returns True to go."""
    body = (f"Changing “{feature}” makes the headphones disconnect and "
            f"reboot.")
    if extra:
        body += "\n\n" + extra
    body += "\n\nThe app will reconnect automatically after a few seconds. Continue?"
    return QMessageBox.warning(
        parent, "Headphones will reconnect", body,
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Ok


class ControlsPanel(QWidget):
    def __init__(self, connection: DeviceConnection, reboot_handler) -> None:
        super().__init__()
        self._conn = connection
        self._reboot = reboot_handler
        self._loading = False
        self._btn_func = None
        self._pending: set = set()
        from .protocol.messages import CUSTOM_BTN_FUNCS

        lay = QVBoxLayout(self)
        box = QGroupBox("Controls")
        self._form = QFormLayout(box)
        self._custom = QComboBox()
        for val, name in CUSTOM_BTN_FUNCS:
            self._custom.addItem(name, val)
        self._custom.activated.connect(self._apply_custom)
        self._touch = QCheckBox("Touch sensor control panel")
        self._touch.toggled.connect(self._apply_touch)
        self._pause = QCheckBox("Pause when headphones are removed")
        self._pause.toggled.connect(self._apply_pause)
        self._form.addRow("CUSTOM button:", self._custom)
        self._form.addRow(self._touch)
        self._form.addRow(self._pause)
        lay.addWidget(box)
        lay.addStretch(1)

    def _apply_custom(self, index: int) -> None:
        if self._loading:
            return
        func = int(self._custom.itemData(index))
        if not _confirm_reboot(self, "CUSTOM button function"):
            self._restore_custom()
            return
        self._btn_func = func
        self._conn.set_custom_button(func)
        self._reboot()

    def _restore_custom(self) -> None:
        self._loading = True
        try:
            i = self._custom.findData(self._btn_func)
            if i >= 0:
                self._custom.setCurrentIndex(i)
        finally:
            self._loading = False

    def _apply_touch(self, on: bool) -> None:
        if not self._loading:
            self._conn.set_touch_panel(on)
            _mark_pending(self._pending, self._touch)

    def _apply_pause(self, on: bool) -> None:
        if not self._loading:
            self._conn.set_auto_pause(on)
            _mark_pending(self._pending, self._pause)

    def clear_inflight(self) -> None:
        self._pending.clear()
        self._touch.setEnabled(True)
        self._pause.setEnabled(True)

    def update_state(self, st: DeviceState, confirmed: bool = False) -> None:
        if confirmed:
            self._pending.clear()
        self._loading = True
        try:
            _set_row_visible(self._form, self._custom, st.custom_button is not None)
            self._touch.setVisible(st.touch_panel is not None)
            self._pause.setVisible(st.auto_pause is not None)
            # CUSTOM button reboots the headset, so it isn't part of the
            # in-flight guard (its value is re-read on reconnect).
            if st.custom_button is not None:
                self._btn_func = st.custom_button
                i = self._custom.findData(st.custom_button)
                if i >= 0:
                    self._custom.setCurrentIndex(i)
            if st.touch_panel is not None and self._touch not in self._pending:
                self._touch.setChecked(bool(st.touch_panel))
                self._touch.setEnabled(True)
            if st.auto_pause is not None and self._pause not in self._pending:
                self._pause.setChecked(bool(st.auto_pause))
                self._pause.setEnabled(True)
        finally:
            self._loading = False


class ConnectivityPanel(QWidget):
    def __init__(self, connection: DeviceConnection, reboot_handler) -> None:
        super().__init__()
        self._conn = connection
        self._reboot = reboot_handler
        self._loading = False
        self._sq_mode = 0
        from .protocol.messages import SOUND_QUALITY_MODES

        lay = QVBoxLayout(self)
        box = QGroupBox("Connectivity")
        self._form = QFormLayout(box)
        self._sq = QComboBox()
        for val, name in SOUND_QUALITY_MODES:
            self._sq.addItem(name, val)
        self._sq.activated.connect(self._apply_sq)
        self._mp = QCheckBox("Connect to 2 devices simultaneously")
        self._mp.toggled.connect(self._apply_mp)
        self._form.addRow("Sound quality mode:", self._sq)
        self._form.addRow(self._mp)
        lay.addWidget(box)
        note = QLabel("Multipoint and Stable-Connection mode disable LDAC. "
                      "Changing either reconnects the headphones.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        lay.addWidget(note)
        lay.addStretch(1)

    def _apply_sq(self, index: int) -> None:
        if self._loading:
            return
        mode = int(self._sq.itemData(index))
        if not _confirm_reboot(self, "Sound quality mode",
                               "Stable Connection disables LDAC."):
            self._loading = True
            try:
                i = self._sq.findData(self._sq_mode)
                if i >= 0:
                    self._sq.setCurrentIndex(i)
            finally:
                self._loading = False
            return
        self._sq_mode = mode
        self._conn.set_sound_quality(mode)
        self._reboot()

    def _apply_mp(self, on: bool) -> None:
        if self._loading:
            return
        if not _confirm_reboot(self, "Connect to 2 devices",
                               "LDAC cannot be used while connected to 2 devices."):
            self._loading = True
            try:
                self._mp.setChecked(not on)
            finally:
                self._loading = False
            return
        self._conn.set_multipoint(on)
        self._reboot()

    def update_state(self, st: DeviceState, confirmed: bool = False) -> None:
        self._loading = True
        try:
            # per-control gating: show a control only if the model reports it
            _set_row_visible(self._form, self._sq, st.sound_quality is not None)
            self._mp.setVisible(st.multipoint is not None)
            if st.sound_quality is not None:
                self._sq_mode = st.sound_quality
                i = self._sq.findData(st.sound_quality)
                if i >= 0:
                    self._sq.setCurrentIndex(i)
            if st.multipoint is not None:
                self._mp.setChecked(bool(st.multipoint))
        finally:
            self._loading = False


class PlaceholderPanel(QWidget):
    def __init__(self, feature: str) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        msg = QLabel(f"{feature} — coming soon.\n\nThe command layout for this "
                     f"feature still needs to be confirmed on-device before it "
                     f"can be wired up safely.")
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet("color: gray;")
        lay.addWidget(msg)
        self.setEnabled(False)


# ---------------------------------------------------------------------------
# One tab per headset
# ---------------------------------------------------------------------------

class DeviceTab(QWidget):
    def __init__(self, mac: str, name: str, supported: bool = True) -> None:
        super().__init__()
        self.mac = mac
        self.name = name
        self._supported = supported

        outer = QVBoxLayout(self)

        # Connection is manual on purpose: opening the app or rescanning must
        # never open/close the config channel by itself (that can make the
        # headset power-cycle). The user presses Connect when ready.
        bar = QHBoxLayout()
        self._status = QLabel("Not connected")
        self._status.setStyleSheet("font-weight: bold;")
        bar.addWidget(self._status, 1)
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._toggle_connect)
        bar.addWidget(self._connect_btn)
        outer.addLayout(bar)

        # Devices that don't advertise the Sony MDR config service (e.g. the
        # original MDR-1000X) can't be controlled by this protocol — say so
        # clearly instead of failing to connect.
        if not supported:
            self._read_only_info(mac, name, outer)
            return

        self._conn = DeviceConnection(mac, name)
        self._connected = False

        self._sub = QTabWidget()
        self._info = InfoPanel()
        self._noise = NoiseAmbientPanel(self._conn)
        self._battery = BatteryPanel(self._conn)
        self._eq = EqualizerPanel(self._conn)
        self._stc = SpeakToChatPanel(self._conn)
        self._dsee = DseePanel(self._conn)
        self._controls = ControlsPanel(self._conn, self.begin_reconnect)
        self._connectivity = ConnectivityPanel(self._conn, self.begin_reconnect)
        self._sub.addTab(self._info, "Info")
        self._sub.addTab(self._noise, "Noise && Ambient")
        self._sub.addTab(self._battery, "Battery")
        self._sub.addTab(self._eq, "Equalizer")
        self._sub.addTab(self._stc, "Speak-to-Chat")
        self._sub.addTab(self._dsee, "DSEE")
        self._sub.addTab(self._controls, "Controls")
        self._sub.addTab(self._connectivity, "Connectivity")
        self._panels = (self._info, self._noise, self._battery, self._eq,
                        self._stc, self._dsee, self._controls, self._connectivity)
        outer.addWidget(self._sub)

        self._conn.statusChanged.connect(self._on_status)
        self._conn.stateChanged.connect(self._on_state)
        self._conn.settingApplied.connect(self._on_setting_applied)
        self._conn.errorOccurred.connect(self._on_error)

    def _toggle_connect(self) -> None:
        if self._connected:
            self._conn.disconnect()
            self._connected = False
            self._connect_btn.setText("Connect")
            self._status.setText("Not connected")
        else:
            self._connected = True
            self._connect_btn.setText("Disconnect")
            self._conn.start()

    def _on_status(self, status: str) -> None:
        pretty = {"connecting": "Connecting…", "ready": "Connected",
                  "disconnected": "Disconnected", "idle": "Not connected",
                  "rebooting": "Applying — headphones rebooting, reconnecting…",
                  }.get(status, status)
        self._status.setText(pretty)
        # keep the Connect/Disconnect button in sync with the real state
        if status in ("disconnected", "idle"):
            self._connected = False
            self._connect_btn.setText("Connect")
        elif status in ("connecting", "ready", "rebooting"):
            self._connected = True
            self._connect_btn.setText("Disconnect")

    def _on_state(self, st: DeviceState, confirmed: bool = False) -> None:
        for panel in self._panels:
            panel.update_state(st, confirmed)
        self._apply_gating(st)
        if st.model_name:
            self.name = st.model_name

    def _on_setting_applied(self, st: DeviceState) -> None:
        # A single write completed and was read back: this is the authoritative
        # confirmation for whichever control was in flight.
        self._on_state(st, confirmed=True)

    def _apply_gating(self, st: DeviceState) -> None:
        """Show only the features the connected model actually reports. A feature
        whose state never came back during the handshake is hidden — this is what
        lets older models (WH-1000XM3, MDR-1000X) expose their smaller feature set
        without dead tabs. Info + Battery are always shown."""
        available = {
            self._noise: st.ncasm is not None,
            self._eq: st.eq is not None,
            self._stc: st.stc is not None,
            self._dsee: st.dsee is not None,
            self._controls: any(v is not None for v in
                                (st.custom_button, st.touch_panel, st.auto_pause)),
            self._connectivity: any(v is not None for v in
                                    (st.sound_quality, st.multipoint)),
        }
        for widget, ok in available.items():
            idx = self._sub.indexOf(widget)
            if idx >= 0:
                self._sub.setTabVisible(idx, ok)

    def begin_reconnect(self) -> None:
        """After a reboot-inducing command: show status and auto-reconnect.
        The worker also emits 'rebooting'; we schedule the reconnect here."""
        self._on_status("rebooting")
        QTimer.singleShot(15000, self._conn.reconnect)

    def _on_error(self, msg: str) -> None:
        self._status.setText(f"Error: {msg}")
        # A write may have failed — release any in-flight controls so they don't
        # stay disabled forever waiting for a confirmation that won't come.
        for panel in self._panels:
            if hasattr(panel, "clear_inflight"):
                panel.clear_inflight()

    def _read_only_info(self, mac: str, name: str, outer) -> None:
        """For models without the Sony config service (e.g. MDR-1000X): no MDR
        control, but still show what the system knows — model, battery, codec."""
        from .device import DeviceState
        from .protocol import messages
        from .protocol.enums import PowerInquiredType
        from .transport import bluez

        self._conn = None
        self._panels = ()
        self._connect_btn.setEnabled(False)
        self._connect_btn.setVisible(False)
        self._status.setText("Read-only (no config service)")

        self._sub = QTabWidget()
        self._info = InfoPanel()
        self._sub.addTab(self._info, "Info")
        outer.addWidget(self._sub)
        note = QLabel("This model doesn't expose the Sony configuration service, "
                      "so its settings can't be changed here (it predates the MDR "
                      "config protocol). Showing basic info from the system.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        outer.addWidget(note)

        st = DeviceState(mac=mac, model_id=name)
        pct = bluez.battery_percentage(mac)
        if pct is not None:
            st.battery = messages.BatteryStatus(
                kind=PowerInquiredType.BATTERY, level=pct, charging=False)
        st.codec = bluez.active_codec(mac)
        self._info.update_state(st)

    def shutdown(self) -> None:
        if self._conn is not None:
            self._conn.shutdown()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Sony Headphone Support {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(560, 460)
        self._pool = QThreadPool.globalInstance()
        self._tabs_by_mac: dict[str, DeviceTab] = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        header.addWidget(QLabel("Headphone:"))
        self._picker = QComboBox()
        self._picker.setMinimumWidth(280)
        self._picker.currentIndexChanged.connect(self._on_picker)
        header.addWidget(self._picker, 1)
        self._rescan = QPushButton("Rescan")
        self._rescan.clicked.connect(self.rescan)
        header.addWidget(self._rescan)
        root.addLayout(header)

        # centered product image, under the header row and above the tabs
        self._device_image = QLabel()
        self._device_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._device_image.setVisible(False)
        root.addWidget(self._device_image)

        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab)
        root.addWidget(self._tabs)

        self._empty = QLabel("Scanning for headphones…")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._empty)

        self._quitting = False
        self._build_tray()
        self.rescan()

    # -- system tray -------------------------------------------------------

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        self._tray = QSystemTrayIcon(app_icon(), self)
        self._tray.setToolTip("Sony Headphone Support")
        menu = QMenu()
        self._act_show = menu.addAction("Show / Hide")
        self._act_show.triggered.connect(self._toggle_window)
        act_rescan = menu.addAction("Rescan")
        act_rescan.triggered.connect(self.rescan)
        menu.addSeparator()
        act_quit = menu.addAction("Quit")
        act_quit.triggered.connect(self._quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window()

    def _toggle_window(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _quit(self) -> None:
        self._quitting = True
        self.close()
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()

    # -- scanning ----------------------------------------------------------

    def rescan(self) -> None:
        self._rescan.setEnabled(False)
        self._empty.setText("Scanning for headphones…")
        self._empty.setVisible(self._tabs.count() == 0)
        worker = ScanWorker()
        worker.signals.finished.connect(self._on_scanned)
        worker.signals.error.connect(self._on_scan_error)
        self._pool.start(worker)

    def _on_scanned(self, devices: list) -> None:
        self._rescan.setEnabled(True)
        found = {d.mac: d for d in devices}
        # remove tabs for headsets that are no longer connected
        for mac in list(self._tabs_by_mac):
            if mac not in found:
                self._remove_device(mac)
        # add newly-connected headsets
        for mac, dev in found.items():
            if mac not in self._tabs_by_mac:
                self._add_device(mac, dev.name, dev.has_service)
        self._empty.setVisible(self._tabs.count() == 0)
        if self._tabs.count() == 0:
            self._empty.setText("No connected Sony headphones found.\n"
                                "Connect one over Bluetooth, then press Rescan.")

    def _on_scan_error(self, msg: str) -> None:
        self._rescan.setEnabled(True)
        self._empty.setVisible(True)
        self._empty.setText(f"Scan failed: {msg}")

    def _add_device(self, mac: str, name: str, supported: bool = True) -> None:
        tab = DeviceTab(mac, name, supported=supported)
        self._tabs_by_mac[mac] = tab
        idx = self._tabs.addTab(tab, name)
        self._picker.addItem(name, mac)
        self._tabs.setCurrentIndex(idx)
        self._update_device_image()

    def _remove_device(self, mac: str) -> None:
        tab = self._tabs_by_mac.pop(mac, None)
        if tab is None:
            return
        tab.shutdown()
        idx = self._tabs.indexOf(tab)
        if idx >= 0:
            self._tabs.removeTab(idx)
        pidx = self._picker.findData(mac)
        if pidx >= 0:
            self._picker.removeItem(pidx)
        tab.deleteLater()
        self._update_device_image()

    # -- dropdown <-> tab sync --------------------------------------------

    def _on_picker(self, index: int) -> None:
        if 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)

    def _on_tab(self, index: int) -> None:
        if 0 <= index < self._picker.count() and self._picker.currentIndex() != index:
            self._picker.setCurrentIndex(index)
        self._update_device_image()

    def _update_device_image(self) -> None:
        name = ""
        idx = self._tabs.currentIndex()
        if idx >= 0:
            name = getattr(self._tabs.widget(idx), "name", "")
        for key, fname in MODEL_IMAGES.items():
            if key in name:
                pm = QPixmap(_resource(fname))
                if not pm.isNull():
                    self._device_image.setPixmap(pm.scaledToHeight(
                        150, Qt.TransformationMode.SmoothTransformation))
                    self._device_image.setVisible(True)
                    return
        # No product image on disk (they aren't shipped) — fall back to the themed
        # headphone icon rather than leaving an empty gap.
        icon = app_icon().pixmap(128, 128)
        if not icon.isNull():
            self._device_image.setPixmap(icon)
            self._device_image.setVisible(True)
        else:
            self._device_image.setVisible(False)

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        # Closing the window hides to tray; real exit is the tray's Quit action.
        if self._tray is not None and not self._quitting:
            event.ignore()
            self.hide()
            return
        for tab in self._tabs_by_mac.values():
            tab.shutdown()
        super().closeEvent(event)
