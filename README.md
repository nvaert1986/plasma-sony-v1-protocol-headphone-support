# plasma-sony-v1-protocol-headphone-support

A **PyQt6** desktop app for **KDE Plasma** (and any Linux desktop) that configures
**Sony WH-1000XM3 / WH-1000XM4** headphones over Bluetooth, by speaking Sony's own
**MDR protocol** directly over Bluetooth Classic (RFCOMM). Adjust noise
cancelling / ambient sound, the equalizer, Speak-to-Chat, DSEE, the physical
controls and connectivity options from your desktop instead of reaching for your
phone.

It talks to the headset the same way Sony's *Sound Connect* app does on a phone,
but natively on Linux, and it reads back what the headset is actually set to, so
the UI reflects the real device state rather than guessing.

**Version 1.1.2** — see the [Changelog](#changelog).

---

> # ❗ USE AT YOUR OWN RISK
> **This software talks directly to your headphones over Sony's Bluetooth control
> protocol. It is provided "as is", with NO WARRANTY of any kind. The author is
> NOT responsible for any damage, misconfiguration, loss of settings, firmware
> issues, or other problems that may result from using it. By using this software
> you accept full responsibility.**

---

## What it does

- Detects **connected Sony headsets** (recognised by the Sony config service or
  Sony's `WH-` / `WF-` / `WI-` / `MDR-` / LinkBuds / INZONE / ULT naming). One tab
  per headset, with a dropdown to switch between them and a **Rescan** button.
- **Reads the current state on connect** and shows it live: it fetches the
  headset's **existing settings** (noise/ambient level, equalizer curve,
  Speak-to-Chat, DSEE, button assignments, connectivity options) so every control
  starts on the value the headset is really using, not a default.
- **Battery level** display, read from the system's Bluetooth stack (BlueZ).
- **Active codec** display (SBC / AAC / aptX / aptX HD / LDAC) plus DSEE status, so
  you can see exactly how audio is being carried.
- **Noise Cancelling / Ambient Sound** with Focus-on-Voice.
- **Equalizer**: presets plus a 6-band custom curve (Clear Bass + 5 bands),
  pre-filled from the headset's current curve.
- **Speak-to-Chat** (enable, sensitivity, timeout) and **DSEE** upscaling.
- **Controls**: CUSTOM button function, touch-sensor panel, and pause-when-removed.
- **Connectivity**: Sound Quality Mode (Prioritize Sound Quality / Stable
  Connection) and Multipoint (connect to two devices), handled reboot/reconnect
  aware so the app warns, applies, and reconnects on its own.
- **Capability-driven**: on connect the app asks the headset which functions it
  supports and only shows those, so each model exposes exactly the tabs it has, with
  no per-model hardcoding.
- Lives in the **system tray** with a proper headphone icon and a per-model product
  image.

Headsets that don't expose the Sony config service (for example the original
**MDR-1000X**) are still shown with a **read-only Information** tab (model, battery,
codec); non-Sony devices are excluded entirely.

## Tested & confirmed working

The app is capability-driven, so other v1-era Sony headsets should work without
changes, but these are the units verified on real hardware:

| Model | Firmware | Status |
|---|---|---|
| Sony **WH-1000XM3** (×2 units) | **4.5.2** | ✅ Confirmed working |
| Sony **WH-1000XM4** | **3.0.1** | ✅ Confirmed working |

Both models were tested end to end: connecting, reading back existing settings, and
changing every exposed control, on the firmware versions listed above.

Other Sony headphones that use the same **MDR v1/table1** protocol (for example
WF-1000XM3, WI-1000XM2, and various WH-XB / WH-CH models) are expected to work and
are capability-gated, but are **untested**. WH/WF-1000XM5, XM6 and LinkBuds use a
newer **v2/table2** protocol that is not implemented yet.

## Requirements

| Requirement | Notes |
|---|---|
| **OS** | Linux with **KDE Plasma** recommended (works on other desktops too). |
| **Python** | 3.10 or newer. |
| **PyQt6** | via your distro package or `pip`. |
| **BlueZ** | with the headset **paired and trusted** (`bluetoothctl`). |
| **Bluetooth Classic (BR/EDR)** | the control protocol is RFCOMM, not BLE. |

See [`INSTALL.md`](INSTALL.md) for the full setup, desktop integration, and
troubleshooting.

## Installation (quick start)

```bash
# 1. Pair and trust the headset once (bluetoothctl).
# 2. Install PyQt6 (distro package preferred), e.g. on Gentoo:
sudo emerge -av dev-python/PyQt6
#    or:  pip install -r requirements.txt   (ideally in a virtualenv)

# 3. Run
python3 main.py
```

Full instructions, including a headless CLI check and the optional launcher entry,
are in [`INSTALL.md`](INSTALL.md).

## Platform support

Developed and tested on **Gentoo Linux** (KDE Plasma, Wayland). Other
distributions with Plasma and a working BlueZ stack should work too, but are
untested.

## ⚠️ Limitations & known quirks

- **This is early software and may contain bugs.** It talks directly to your
  headphones; see the risk notice above.
- **XM3 equalizer is only usable in SBC mode.** On the WH-1000XM3, the graphic
  equalizer and **LDAC cannot coexist**: engaging the EQ forces the link down to
  SBC. This is device behaviour (Sony's own app shows the same), not a bug here, so
  the app **disables the equalizer while LDAC is active on the XM3** and shows a note
  to switch Sound Quality to *Prioritize Stable Connection* first. The XM4
  (Bluetooth 5.0) is not affected and keeps the EQ enabled at all times.
- **Reboot-inducing settings drop the link briefly.** Sound Quality Mode, Multipoint
  and the CUSTOM button cause the headset to restart; the app warns, applies, and
  auto-reconnects after a few seconds. This is expected.
- **A feature the headset has is not guaranteed to be remotely controllable** — the
  app only exposes what the headset advertises as supported.
- **Phone-only features are out of scope**: 360 Reality Audio (needs a personal
  hearing profile) and Adaptive Sound Control (needs the phone's motion/location
  sensors). See [`ROADMAP.md`](ROADMAP.md).

## Changelog

### 1.1.2
- **Noise Cancelling / Ambient Sound (WH-1000XM4) corrected.** Ambient levels now
  hold (including level 1), unchecking Ambient properly switches to Noise
  Cancelling, and Focus-on-Voice works. An earlier build wrote the ambient level
  into the noise-cancelling field, which dropped the headset out of ambient.
- **Ambient level slider starts at 1** — matches Sony's numbering (level 0 is the
  noise-cancelling end of the scale).
- **No more setting "flicker".** Each change is confirmed by reading back only that
  one setting and holding the control until the headset confirms, so a control no
  longer briefly snaps back to its previous value.
- **Protocol reference verified against both the WH-1000XM3 and WH-1000XM4** and
  expanded (feature matrix + EQ / STC / DSEE / touch / Auto-Power-Off byte layouts);
  see [`docs/SONY_WH1000_XM3_XM4_PROTOCOL.md`](docs/SONY_WH1000_XM3_XM4_PROTOCOL.md).

### 1.1.1
- **XM3 equalizer gating** — the equalizer is automatically disabled while LDAC is
  active on the WH-1000XM3 (with a note to switch to a stable-connection / SBC mode),
  since engaging the EQ on that model forces the codec to SBC. The XM4 keeps the EQ
  enabled at all times.
- Stability fixes around per-setting state refresh, so controls (including
  Focus-on-Voice and the touch-panel toggle) reliably reflect the headset after each
  change.

### 1.1
- **WH-1000XM3 support confirmed** (firmware 4.5.2), alongside the WH-1000XM4
  (firmware 3.0.1).
- **Reads existing settings on connect** and **battery level** display, plus the
  active **codec** (SBC / AAC / aptX / aptX HD / LDAC) and DSEE status on the
  Information tab.
- **Equalizer** pre-fills from the headset's current curve; presets plus a 6-band
  custom curve.
- **Capability-driven per-model layout** — touch / multipoint / assignable-key slots
  are mapped by their advertised capability title, and Auto Power Off options are
  built from what the headset reports, so the XM3 and XM4 each show their correct
  controls.
- **Reboot/reconnect-aware controls** for Sound Quality Mode, Multipoint and the
  CUSTOM button.
- System tray, per-model product image, and Sony-only device gating.

### 1.0
- Initial release for the WH-1000XM4: discovery, connect/handshake, device
  Information, battery, NC / Ambient + Focus-on-Voice, equalizer, Speak-to-Chat,
  DSEE, controls (CUSTOM button, touch panel, pause-when-removed), and connectivity
  (Sound Quality Mode, Multipoint). Built on a headless, unit-tested protocol
  package.

## Credits & basis

This project used **[Plutoberth/SonyHeadphonesClient](https://github.com/Plutoberth/SonyHeadphonesClient)**
as its basis: that client (and the wider reverse-engineering community around it) is
where the MDR framing and command groundwork came from. This app then built on and
**improved upon** that work for a Linux / PyQt setting, in particular by:

- **displaying the battery level**,
- **fetching the headset's existing settings on connect** so the UI reflects the
  real device state, and
- doing the same for **equalizer support** (the current EQ curve is read back and
  pre-filled, not assumed).

Because it draws on that **GPL-3.0-licensed** groundwork, this project is also
released under **GPL-3.0-or-later** (see [License](#license)).

Protocol byte layouts were additionally cross-checked against Sony's own
`com.sony.songpal.tandemfamily` **v1/table1** enums (decompiled from the Sony Sound
Connect app *for interoperability study only* — the decompiled app is **not**
distributed with this project) and against live HCI captures. See
[`README-TECHNICAL.md`](README-TECHNICAL.md) and
[`docs/SONY_WH1000_XM3_XM4_PROTOCOL.md`](docs/SONY_WH1000_XM3_XM4_PROTOCOL.md) for
the technical detail.

Not affiliated with, endorsed by, or sponsored by Sony. "Sony", "WH-1000XM4",
"WH-1000XM3" and related marks are trademarks of their respective owners, used here
only descriptively to identify the compatible hardware. Built for interoperability.

## Development note

Most of this project was **written by Claude** (Anthropic's AI assistant), but it
was **controlled, tested and verified by a human** — both the **code** and against
**real hardware** (the WH-1000XM3 and WH-1000XM4 units listed above). As with any
software, and especially AI-assisted code that talks to hardware, it may still
contain bugs. See the risk notice at the top.

## License

Licensed under the **GNU General Public License, version 3 or later
(GPL-3.0-or-later)** — full text in [`LICENSE`](LICENSE). This choice follows the
GPL-3.0-licensed prior work it builds on (see [Credits & basis](#credits--basis)).

You may use, study, share, and modify it under the GPL's terms; derivative works
must remain GPL-compatible. The software is provided **as-is, without warranty** of
any kind (see the risk notice above and sections 15–16 of the licence).

**Not included in this repository** (and excluded via `.gitignore`), because they
are not ours to redistribute:

- the decompiled Sony Sound Connect app (Sony's copyrighted code — used locally for
  interoperability study only),
- Sony product images / marketing renders,
- third-party tools (jadx, apktool),
- raw HCI captures (they contain a real Bluetooth address).
