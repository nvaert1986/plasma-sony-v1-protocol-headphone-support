"""Background worker plumbing (Qt).

Discovery is a quick one-shot on the global thread pool. Each headset gets its
own persistent :class:`DeviceConnection` — a QObject that owns a QThread running
a :class:`_DeviceWorker`, which holds the blocking RFCOMM session. Widgets are
only ever touched on the GUI thread via the queued signals defined here.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QObject, QRunnable, QThread, QTimer, pyqtSignal, pyqtSlot,
)

from .device import DeviceState, Headphones
from .transport import discovery

log = logging.getLogger(__name__)

BATTERY_POLL_MS = 30_000  # periodic battery/state refresh


class ScanSignals(QObject):
    finished = pyqtSignal(list)   # list[discovery.DiscoveredDevice]
    error = pyqtSignal(str)


class ScanWorker(QRunnable):
    """Run a BlueZ scan off the GUI thread."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = ScanSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            devices = discovery.scan()
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))
        else:
            self.signals.finished.emit(devices)


class _DeviceWorker(QObject):
    """Lives on its own QThread; owns the blocking Headphones session."""

    stateChanged = pyqtSignal(object)   # DeviceState — full/background refresh
    settingApplied = pyqtSignal(object)  # DeviceState — confirmation of one write
    statusChanged = pyqtSignal(str)     # "connecting" | "ready" | "disconnected"
    errorOccurred = pyqtSignal(str)

    def __init__(self, mac: str) -> None:
        super().__init__()
        self._hp = Headphones(mac)
        self._timer: QTimer | None = None

    @pyqtSlot()
    def start(self) -> None:
        self.statusChanged.emit("connecting")
        try:
            self._hp.connect()
            state = self._hp.handshake()
        except Exception as exc:  # noqa: BLE001
            self.errorOccurred.emit(str(exc))
            self.statusChanged.emit("disconnected")
            return
        self.stateChanged.emit(state)
        self.statusChanged.emit("ready")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(BATTERY_POLL_MS)

    @pyqtSlot()
    def _poll(self) -> None:
        if not self._hp.connected:
            return
        try:
            state = self._hp.sync()
        except Exception as exc:  # noqa: BLE001
            self.errorOccurred.emit(str(exc))
            return
        self.stateChanged.emit(state)

    @pyqtSlot(bool, bool, int)
    def setNcAsm(self, enabled: bool, focus_on_voice: bool, asm_level: int) -> None:
        self._apply(lambda: self._hp.set_ncasm(
            enabled=enabled, focus_on_voice=focus_on_voice, asm_level=asm_level))

    @pyqtSlot(list)
    def setEqBands(self, bands: list) -> None:
        self._apply(lambda: self._hp.set_eq_bands([int(b) for b in bands]))

    @pyqtSlot(int)
    def setEqPreset(self, preset_id: int) -> None:
        self._apply(lambda: self._hp.set_eq_preset(preset_id))

    @pyqtSlot(bool, int, int)
    def setStc(self, enabled: bool, sensitivity: int, timeout: int) -> None:
        self._apply(lambda: self._hp.set_stc(enabled, sensitivity, timeout))

    @pyqtSlot(bool)
    def setDsee(self, on: bool) -> None:
        self._apply(lambda: self._hp.set_dsee(on))

    @pyqtSlot(int)
    def setSoundQuality(self, mode: int) -> None:
        self._apply_reboot(lambda: self._hp.set_sound_quality(mode))

    @pyqtSlot(int)
    def setAutoPowerOff(self, element: int) -> None:
        self._apply(lambda: self._hp.set_auto_power_off(element))

    @pyqtSlot(int)
    def setCustomButton(self, func: int) -> None:
        self._apply_reboot(lambda: self._hp.set_custom_button(func))

    @pyqtSlot(bool)
    def setTouchPanel(self, on: bool) -> None:
        self._apply(lambda: self._hp.set_touch_panel(on))

    @pyqtSlot(bool)
    def setAutoPause(self, on: bool) -> None:
        self._apply(lambda: self._hp.set_auto_pause(on))

    @pyqtSlot(bool)
    def setMultipoint(self, on: bool) -> None:
        self._apply_reboot(lambda: self._hp.set_multipoint(on))

    def _apply(self, action) -> None:
        # device.py already read back the ONE feature it changed, so the held
        # state reflects the committed value. We deliberately do NOT re-read the
        # whole device here: that burst is what made a control flicker A->B->A
        # (a stale read landing before the device committed) and what flapped
        # LDAC on the XM3. Emit as settingApplied so the GUI treats it as the
        # confirmation for its in-flight control.
        try:
            action()
        except Exception as exc:  # noqa: BLE001
            self.errorOccurred.emit(str(exc))
            return
        self.settingApplied.emit(self._hp.state)

    def _apply_reboot(self, action) -> None:
        """Reboot-inducing change: send it (device.py auto-confirms the alert),
        then close — the headset reboots and the GUI reconnects. Do NOT sync a
        dying link."""
        if self._timer:
            self._timer.stop()
        try:
            action()
        except Exception as exc:  # noqa: BLE001 — link drops on reboot, expected
            log.debug("reboot command dropped the link (expected): %s", exc)
        try:
            self._hp.close()
        except Exception:  # noqa: BLE001
            pass
        self.statusChanged.emit("rebooting")

    @pyqtSlot()
    def refresh(self) -> None:
        self._poll()

    @pyqtSlot()
    def stop(self) -> None:
        if self._timer:
            self._timer.stop()
        self._hp.close()
        self.statusChanged.emit("disconnected")


class DeviceConnection(QObject):
    """GUI-thread handle for one headset. Re-emits worker signals; forwards
    requests to the worker via queued signals (thread-safe)."""

    stateChanged = pyqtSignal(object)
    settingApplied = pyqtSignal(object)
    statusChanged = pyqtSignal(str)
    errorOccurred = pyqtSignal(str)

    _reqStart = pyqtSignal()
    _reqSetNcAsm = pyqtSignal(bool, bool, int)
    _reqSetEqBands = pyqtSignal(list)
    _reqSetEqPreset = pyqtSignal(int)
    _reqSetStc = pyqtSignal(bool, int, int)
    _reqSetDsee = pyqtSignal(bool)
    _reqSetSoundQuality = pyqtSignal(int)
    _reqSetApo = pyqtSignal(int)
    _reqSetCustomButton = pyqtSignal(int)
    _reqSetTouchPanel = pyqtSignal(bool)
    _reqSetAutoPause = pyqtSignal(bool)
    _reqSetMultipoint = pyqtSignal(bool)
    _reqRefresh = pyqtSignal()
    _reqStop = pyqtSignal()

    def __init__(self, mac: str, name: str) -> None:
        super().__init__()
        self.mac = mac
        self.name = name
        self.state: DeviceState | None = None
        self.status = "idle"

        self._thread = QThread()
        self._worker = _DeviceWorker(mac)
        self._worker.moveToThread(self._thread)

        self._worker.stateChanged.connect(self._on_state)
        self._worker.settingApplied.connect(self._on_setting_applied)
        self._worker.statusChanged.connect(self._on_status)
        self._worker.errorOccurred.connect(self.errorOccurred)

        self._reqStart.connect(self._worker.start)
        self._reqSetNcAsm.connect(self._worker.setNcAsm)
        self._reqSetEqBands.connect(self._worker.setEqBands)
        self._reqSetEqPreset.connect(self._worker.setEqPreset)
        self._reqSetStc.connect(self._worker.setStc)
        self._reqSetDsee.connect(self._worker.setDsee)
        self._reqSetSoundQuality.connect(self._worker.setSoundQuality)
        self._reqSetApo.connect(self._worker.setAutoPowerOff)
        self._reqSetCustomButton.connect(self._worker.setCustomButton)
        self._reqSetTouchPanel.connect(self._worker.setTouchPanel)
        self._reqSetAutoPause.connect(self._worker.setAutoPause)
        self._reqSetMultipoint.connect(self._worker.setMultipoint)
        self._reqRefresh.connect(self._worker.refresh)
        self._reqStop.connect(self._worker.stop)

        self._thread.start()

    # -- request API (call from GUI thread) --------------------------------

    def start(self) -> None:
        self._reqStart.emit()

    def set_ncasm(self, enabled: bool, focus_on_voice: bool, asm_level: int) -> None:
        self._reqSetNcAsm.emit(enabled, focus_on_voice, asm_level)

    def set_eq_bands(self, bands: list) -> None:
        self._reqSetEqBands.emit(bands)

    def set_eq_preset(self, preset_id: int) -> None:
        self._reqSetEqPreset.emit(preset_id)

    def set_stc(self, enabled: bool, sensitivity: int, timeout: int) -> None:
        self._reqSetStc.emit(enabled, sensitivity, timeout)

    def set_dsee(self, on: bool) -> None:
        self._reqSetDsee.emit(on)

    def set_sound_quality(self, mode: int) -> None:
        self._reqSetSoundQuality.emit(mode)

    def set_auto_power_off(self, element: int) -> None:
        self._reqSetApo.emit(element)

    def set_custom_button(self, func: int) -> None:
        self._reqSetCustomButton.emit(func)

    def set_touch_panel(self, on: bool) -> None:
        self._reqSetTouchPanel.emit(on)

    def set_auto_pause(self, on: bool) -> None:
        self._reqSetAutoPause.emit(on)

    def set_multipoint(self, on: bool) -> None:
        self._reqSetMultipoint.emit(on)

    def reconnect(self) -> None:
        """Re-establish the session (used after a device reboot/reconnect)."""
        self._reqStart.emit()

    def refresh(self) -> None:
        self._reqRefresh.emit()

    def disconnect(self) -> None:
        """Close the session but keep the worker thread alive for reconnects."""
        self._reqStop.emit()

    def shutdown(self) -> None:
        self._reqStop.emit()
        self._thread.quit()
        self._thread.wait(3000)

    # -- signal relays -----------------------------------------------------

    def _on_state(self, state: DeviceState) -> None:
        self.state = state
        self.stateChanged.emit(state)

    def _on_setting_applied(self, state: DeviceState) -> None:
        self.state = state
        self.settingApplied.emit(state)

    def _on_status(self, status: str) -> None:
        self.status = status
        self.statusChanged.emit(status)
