# Roadmap

## Status
Released **v1.1.2**, licensed **GPL-3.0-or-later**. Protocol = Sony **MDR v1/table1**
(`com.sony.songpal.tandemfamily.message.mdr`, `DATA_MDR=12`). Confirmed on hardware:
**WH-1000XM4** (fw 3.0.1) and **WH-1000XM3** (fw 4.5.2).

## Implemented (verified on XM3 + XM4)
- Discovery (connected Sony headsets only), connect/disconnect, device Info
- Battery + active codec (via BlueZ) + **Auto Power Off** (capability-driven options)
- Noise Cancelling / Ambient Sound + Focus on Voice
- Equalizer (preset + 6 bands incl. Clear Bass)
- Speak-to-Chat (enable, sensitivity, timeout) · DSEE Extreme (Off/Auto)
- **Controls**: CUSTOM button function, Touch sensor panel, Pause-when-removed
- **Connectivity**: Sound Quality Mode, Multipoint (2 devices)
- Reboot/reconnect-aware controls (warn → apply → auto-reconnect ~15 s):
  CUSTOM button, Sound Quality Mode, Multipoint
- **Capability gatekeeping** — query `CONNECT_GET_SUPPORT_FUNCTION (0x06)` up-front
  and expose only advertised features (**implemented + verified on both models**;
  was the earlier "to verify" refinement)
- **Per-model layout by capability title** — GENERAL_SETTING slots resolved by title
  (XM4 `d1`=touch/`d2`=multipoint; XM3 `d1`=assignable-key/`d2`=touch), APO options
  built from the device's advertised element ids
- **XM3 EQ ↔ LDAC gating** — the EQ is disabled while LDAC is active on the XM3 (the
  two are mutually exclusive on that model), with a note to switch to Stable Connection
- **Event-driven writes** — per-setting targeted read-back + `settingApplied`
  confirmation + in-flight UI guard, so controls don't flicker and MDR traffic stays
  minimal (also avoids flapping LDAC on the XM3)
- System tray, per-model product image (optional; falls back to a themed icon), theme icon

## Verified protocol reference
Full byte-level reference in `docs/SONY_WH1000_XM3_XM4_PROTOCOL.md` §14, resolved from
XM4 HCI captures + an XM3 handshake dump + the decompiled app (v1/table1):
- `protocolVersion` (XM4 `01 00 70 00`, XM3 `01 00 40 10`); Table 2 absent on both.
- Feature matrices: **XM4** 22–23 FunctionTypes, **XM3** 19 (adds VPT `0x41` +
  Sound Position `0x42`; lacks Speak-to-Chat/pause/SYSTEM-CUSTOM-button/multipoint).
- NC/ASM field layout + enum values (**field 5 is the NC ternary, not the level**;
  ambient minimum is level 1); EQ SET layout + signed-level encoding (step = value+10);
  STC/DSEE/touch/APO/pause exact payloads. Earlier 3-way mislabel corrected (CUSTOM
  button = `ASSIGNABLE_SETTINGS 0x06`, pause = `CONTROL_BY_WEARING 0x03`, touch = GS).

## Out of scope (for now)
- **360 Reality Audio** — needs a personal hearing profile (ear photos/measurement).
- **Adaptive Sound Control** — phone-side activity/location context, no standalone command.
- **v2/table2 protocol** (WH/WF-1000XM5, XM6, LinkBuds) — not implemented.
- **BLE transport** — future.

## Remaining gaps / next
- **XM3 assignable (CUSTOM) button** — a *list-type* GENERAL_SETTING (`d1`: NC/ASM ·
  Google Assistant · Amazon Alexa), not the SYSTEM `ASSIGNABLE_SETTINGS` the XM4 uses.
  Needs a **generic GS list control** (title + type + values from the capability),
  which would also cover future models. Currently hidden on the XM3 (XM4's works).
- **Advertised-but-unimplemented FunctionTypes** — VPT `0x41`, Sound Position `0x42`
  (XM3), Voice Guidance `0x39`, NC Optimizer `0x81`, Playback Controller `0xa1`,
  Auto/Adaptive NC `0x71`. Payloads not yet reverse-engineered.
- **Live NTFY listener** — the app currently reflects earcup-button changes on its
  ~30 s poll; a continuous NTFY read loop would make them instant (arming already
  enables the notification stream; not empirically captured yet).
- **Older / cheaper `-N` models** (WH-1000XM2, WH-XB900N, WH-H900N, …) — same
  v1/table1 family, Sony-name-gated + capability-driven, so they *should* connect and
  expose advertised features with no code change, **but the NC/ASM variant especially
  needs on-device verification** (`cli.py <MAC> -v` + a capabilities dump) before
  claiming support. The original **MDR-1000X** has no config service → read-only Info only.
- Optional: name the remaining FunctionType codes (BATTERY_LEVEL, VPT, SOUND_POSITION,
  …) in the app's `FT` table for clearer logging.

## Future
- Rename to a brand-neutral name once other brands are supported (hence the current
  `plasma-sony-v1-protocol-…` name).
- Packaging (.desktop install, KCM integration?).
