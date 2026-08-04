"""Small BlueZ D-Bus helpers.

The WH-1000XM3/XM4 report battery over HFP, which BlueZ exposes as
``org.bluez.Battery1.Percentage`` — not over the MDR config protocol. Reading it
here avoids any MDR probing for battery.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _device_path(bus, mac: str) -> str | None:
    import dbus  # python-dbus

    mgr = dbus.Interface(
        bus.get_object("org.bluez", "/"),
        "org.freedesktop.DBus.ObjectManager",
    )
    suffix = "dev_" + mac.upper().replace(":", "_")
    for path, ifaces in mgr.GetManagedObjects().items():
        if str(path).endswith(suffix):
            return str(path)
    return None


# A2DP vendor codecs keyed by (vendor_id, codec_id), little-endian from the
# MediaTransport1 Configuration blob.
_VENDOR_CODECS = {
    (0x012D, 0x00AA): "LDAC",
    (0x004F, 0x0001): "aptX",
    (0x00D7, 0x0024): "aptX HD",
    (0x00D7, 0x0002): "aptX Low Latency",
    (0x00D7, 0x00AD): "aptX Adaptive",
    (0x053A, 0x4C33): "LHDC",
}


def _codec_name(codec: int, config: bytes) -> str:
    if codec == 0x00:
        return "SBC"
    if codec == 0x02:
        return "AAC"
    if codec == 0xFF and len(config) >= 6:
        vendor = int.from_bytes(config[0:4], "little")
        cid = int.from_bytes(config[4:6], "little")
        return _VENDOR_CODECS.get((vendor, cid), f"Vendor {vendor:#06x}/{cid:#06x}")
    return f"Codec {codec}"


def active_codec(mac: str) -> str | None:
    """Return the negotiated A2DP codec (SBC/AAC/aptX/LDAC/...) from BlueZ, or None."""
    try:
        import dbus

        bus = dbus.SystemBus()
        mgr = dbus.Interface(
            bus.get_object("org.bluez", "/"),
            "org.freedesktop.DBus.ObjectManager",
        )
        dev = "dev_" + mac.upper().replace(":", "_")
        best = None
        for path, ifaces in mgr.GetManagedObjects().items():
            props = ifaces.get("org.bluez.MediaTransport1")
            if props is None or dev not in str(path):
                continue
            codec = int(props.get("Codec", -1))
            config = bytes(bytearray(props.get("Configuration", b"")))
            state = str(props.get("State", ""))
            # prefer an active/pending stream over an idle endpoint
            if best is None or (state in ("active", "pending")
                                and best[2] not in ("active", "pending")):
                best = (codec, config, state)
        if best is None:
            return None
        return _codec_name(best[0], best[1])
    except Exception as exc:  # noqa: BLE001
        log.debug("BlueZ codec read failed for %s: %s", mac, exc)
        return None


def battery_percentage(mac: str) -> int | None:
    """Return the headset battery percentage from BlueZ, or None if unavailable."""
    try:
        import dbus  # python-dbus

        bus = dbus.SystemBus()
        path = _device_path(bus, mac)
        if path is None:
            return None
        props = dbus.Interface(
            bus.get_object("org.bluez", path),
            "org.freedesktop.DBus.Properties",
        )
        return int(props.Get("org.bluez.Battery1", "Percentage"))
    except Exception as exc:  # noqa: BLE001 - dbus/module absence is non-fatal
        log.debug("BlueZ battery read failed for %s: %s", mac, exc)
        return None
