# Installation

Setup for `plasma-sony-v1-protocol-headphone-support`. For what it does and which
devices are confirmed working, see [README.md](README.md).

> **Use at your own risk.** This app sends control commands directly to your
> headphones. It is provided as-is, with no warranty. See the risk notice in the
> README.

## 1. Pair and trust the headset

The app controls a headset that is already paired to this computer, over Bluetooth
Classic (BR/EDR). Pair and trust it once with `bluetoothctl`:

```bash
bluetoothctl
# inside the prompt:
power on
agent on
default-agent
scan on
# ... put the headset in pairing mode, wait for its MAC to appear ...
pair    AC:80:0A:C5:13:01     # your headset's MAC
trust   AC:80:0A:C5:13:01
connect AC:80:0A:C5:13:01
scan off
exit
```

Verify it is connected (should show the headset with `Connected: yes`):

```bash
bluetoothctl info AC:80:0A:C5:13:01
```

If pairing fails, make sure the headset is in pairing mode and no phone is holding
the connection.

## 2. Install PyQt6

Either via your distro (preferred on Gentoo / KDE), or pip:

```bash
# distro examples
# Gentoo:  sudo emerge -av dev-python/PyQt6
# Debian:  sudo apt install python3-pyqt6
# Fedora:  sudo dnf install python3-pyqt6
# Arch:    sudo pacman -S python-pyqt6

# or with pip (ideally in a virtualenv)
pip install -r requirements.txt
```

No other runtime dependency is required. Battery and codec readout use the system
BlueZ D-Bus interface, which is already present on a normal desktop; the control
channel uses Python's standard-library RFCOMM socket.

> Optional: `pybluez2` gives slightly nicer RFCOMM channel resolution (SDP). If it
> is absent, the app falls back to a gentle, validated channel probe and caches the
> result, so it is not needed.

## 3. Run

```bash
cd /path/to/plasma-sony-v1-protocol-headphone-support
python3 main.py
```

The app scans for connected Sony headsets and opens a tab per headset. Use the
dropdown to switch between them, or **Rescan** after connecting one. Closing the
window minimises it to the system tray; quit via the tray menu.

## 4. (Optional) Headless check

Before (or instead of) launching the GUI, you can verify the connection from the
command line:

```bash
# list recognised Sony headsets
python3 cli.py

# connect + dump the handshake for one headset (the on-device confirmation tool)
python3 cli.py AC:80:0A:C5:13:01 -v
```

This is handy if a headset isn't showing up in the GUI, or to confirm the control
channel works at all.

## 5. (Optional) Desktop integration — icon + launcher

Installing the desktop file registers the app so Plasma shows the **headphone icon**
in the task switcher / launcher and app menu.

```bash
# run from the project directory so the correct path is used in Exec=
install -Dm644 plasma-sony-v1-protocol-headphone-support.desktop \
  ~/.local/share/applications/plasma-sony-v1-protocol-headphone-support.desktop
sed -i "s|Exec=python3 .*/main.py|Exec=python3 $PWD/main.py|" \
  ~/.local/share/applications/plasma-sony-v1-protocol-headphone-support.desktop
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

You can then launch it from the app menu, or add it to **System Settings ▸
Autostart** to start it (minimised to tray) on login.

## Troubleshooting

- **No headsets listed** — make sure the headset is **connected** (not just paired):
  `bluetoothctl info <MAC>` should say `Connected: yes`. Connect it, then press
  **Rescan** (or restart the app).
- **Pressing Connect powers the headset off, or it keeps saying "disconnected"** —
  usually a transient RFCOMM issue; wait a few seconds and try again. The app uses a
  cautious channel probe rather than sweeping every channel, so it will not exhaust
  the headset's connection slots.
- **The equalizer is greyed out on the WH-1000XM3** — this is intentional. The XM3
  can't run the EQ and LDAC at the same time, so the EQ is disabled while LDAC is
  active. Set **Sound Quality** to *Prioritize Stable Connection* (Connectivity tab)
  and the equalizer becomes available. The XM4 is not affected.
- **A setting reverts, or the headset briefly "reboots"** — Sound Quality Mode,
  Multipoint and the CUSTOM button restart the headset by design; the app warns,
  applies, and reconnects automatically after a few seconds.
- **Battery or codec shows `—`** — those come from BlueZ; they populate once the
  system has negotiated audio (start playback briefly) and on the next refresh.
- **An older headset connects then shows only an Information tab** — that model
  (for example the original MDR-1000X) does not expose the Sony configuration
  service, so only read-only info is available. This is expected.
