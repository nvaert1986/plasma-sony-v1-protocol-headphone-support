#!/usr/bin/env bash
#
# collect-device-info.sh — gather the information needed to add support for
# another v1-protocol Sony headset (an older or different model).
#
# It runs the SAME vetted, capability-gated handshake the app itself uses and
# dumps only what the headset reports. It is READ-ONLY: it changes no settings
# and sends no writes. Attach the resulting report to a support request.
#
# Requirements:
#   * Python 3.10+                (PyQt6 is NOT needed for this script)
#   * BlueZ + bluetoothctl
#   * the headset paired, trusted, and CONNECTED (bluetoothctl info <MAC> => yes)
#
# Usage:
#   ./collect-device-info.sh              # auto-picks the one connected Sony headset
#   ./collect-device-info.sh AA:BB:CC:DD:EE:FF   # target a specific MAC
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${SCRIPT_DIR}/sony-device-info-${STAMP}.txt"

# ---- preflight ------------------------------------------------------------
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found." >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
    || { echo "ERROR: Python 3.10+ required." >&2; exit 1; }
if [ ! -d "${SCRIPT_DIR}/plasma_sony_headphones" ]; then
    echo "ERROR: run this from inside the project (plasma_sony_headphones/ not found)." >&2
    exit 1
fi

# ---- resolve the target MAC ----------------------------------------------
MAC="${1:-}"
if [ -z "$MAC" ]; then
    echo "Scanning for connected Sony headsets…"
    mapfile -t FOUND < <(cd "$SCRIPT_DIR" && python3 - <<'PY'
import logging; logging.disable(logging.CRITICAL)
from plasma_sony_headphones.transport import discovery
for d in discovery.scan(connected_only=True):
    print(f"{d.mac}\t{d.name}")
PY
)
    if [ "${#FOUND[@]}" -eq 0 ]; then
        echo "No connected Sony headset found. Connect one and retry, or pass its MAC." >&2
        exit 1
    elif [ "${#FOUND[@]}" -gt 1 ]; then
        echo "Multiple Sony headsets connected — re-run with the MAC you want:" >&2
        printf '  %s\n' "${FOUND[@]}" >&2
        exit 1
    fi
    MAC="${FOUND[0]%%$'\t'*}"
    echo "Using: ${FOUND[0]}"
fi

# ---- gather ---------------------------------------------------------------
{
    echo "=============================================================="
    echo " Sony v1-protocol headset — device info report"
    echo " generated: ${STAMP}"
    echo "=============================================================="
    echo
    echo "## System"
    echo "kernel   : $(uname -srmo 2>/dev/null)"
    echo "distro   : $(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}")"
    echo "python   : $(python3 --version 2>&1)"
    echo "bluez    : $(bluetoothctl --version 2>/dev/null || echo 'bluetoothctl not found')"
    echo

    echo "## BlueZ device record"
    if command -v bluetoothctl >/dev/null 2>&1; then
        bluetoothctl info "$MAC" 2>/dev/null | sed 's/^/  /' || echo "  (bluetoothctl info failed)"
    else
        echo "  (bluetoothctl not available)"
    fi
    echo

    CACHE="${HOME}/.cache/plasma-sony-headphones/channels.json"
    echo "## RFCOMM channel cache"
    [ -f "$CACHE" ] && sed 's/^/  /' "$CACHE" || echo "  (none)"
    echo

    echo "## MDR handshake dump (read-only, capability-gated)"
    cd "$SCRIPT_DIR" && python3 - "$MAC" <<'PY'
import sys, logging
logging.disable(logging.CRITICAL)
mac = sys.argv[1]
from plasma_sony_headphones.device import Headphones, MODEL_ID_NAMES
from plasma_sony_headphones.protocol import messages as m
from plasma_sony_headphones.transport import bluez

FT = m.FT
ft_names = {int(getattr(FT, n)): n for n in dir(FT)
            if not n.startswith('_') and isinstance(getattr(FT, n), int)}

def hx(b):
    return b.hex(' ') if b else '(none)'

hp = Headphones(mac)
print(f"  MAC            : {mac}")
try:
    hp.connect()
except Exception as e:            # noqa: BLE001
    print(f"  CONNECT FAILED : {e}")
    print("  (is the headset connected? does it expose the Sony config service?)")
    sys.exit(0)
try:
    st = hp.handshake()
except Exception as e:            # noqa: BLE001
    print(f"  HANDSHAKE FAIL : {e}")
    hp.close()
    sys.exit(0)

known = "yes" if st.model_id in MODEL_ID_NAMES else "NO — NEW MODEL"
print(f"  Model name     : {st.model_name}")
print(f"  Model id       : {st.model_id}   (known to app: {known})")
print(f"  Serial         : {st.serial}")
print(f"  Protocol info  : {hx(st.protocol_raw)}   (all v1/table1 traffic is DATA_MDR=12)")
print(f"  Identifiers    : {st.identifiers}")
print()
print("  Supported functions (CONNECT_RET_SUPPORT_FUNCTION):")
nc_codes = {0x61: 'NOISE_CANCELLING', 0x62: 'NC_AND_ASM',
            0x63: 'AMBIENT_SOUND_MODE', 0x71: 'AUTO_NC_ASM'}
nc_present = []
for c in sorted(st.supported_functions):
    name = ft_names.get(c, '?? (FunctionType not named in app)')
    print(f"    0x{c:02x}  {name}")
    if c in nc_codes:
        nc_present.append(nc_codes[c])
print(f"  -> NC-related FunctionTypes advertised: {', '.join(nc_present) or 'none'}")
print("     (this is the main hint for which NC/ASM SET variant the model needs)")
print()
print("  GENERAL_SETTING slots (title -> slot):")
for k, v in st.gs_slots.items():
    print(f"    {k} = 0x{v:02x}")
print(f"  Auto Power Off options: {[hex(x) for x in st.apo_options]}")
print()
print("  NC/ASM:")
if st.ncasm:
    print(f"    raw RET (via GET 66 02): {hx(st.ncasm.raw)}")
    print(f"    parsed: ambient={st.ncasm.enabled} voice={st.ncasm.focus_on_voice} "
          f"level={st.ncasm.asm_level}")
else:
    print("    No NC/ASM state came back from the 0x02 combined-mode GET.")
    print("    This model likely uses a different NcAsmInquiredType — see the")
    print("    NC-related FunctionTypes above (0x01 / 0x03 vs 0x02).")
print()
print(f"  EQ             : {st.eq}")
print(f"  Battery (BlueZ): {bluez.battery_percentage(mac)}")
print(f"  Codec (BlueZ)  : {bluez.active_codec(mac)}")
hp.close()
PY
    echo
    echo "=============================================================="
    echo " End of report. Please attach this file to your request."
    echo "=============================================================="
} 2>&1 | tee "$OUT"

echo
echo "Saved report to: $OUT"
