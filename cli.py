#!/usr/bin/env python3
"""Headless diagnostic: discover Sony headsets and dump the handshake.

This is the "confirm-on-device" tool from the protocol reference. Run it against
the XM3 and the XM4 to pin down the to-confirm (🔶) fields: protocolVersion,
Table-2 support, the full support-function list, and the initial battery/NC-ASM
state — with no writes to the device.

Usage:
    python cli.py                 # scan and list recognised headsets
    python cli.py <MAC>           # connect + handshake dump for one headset
    python cli.py <MAC> --raw     # also print every raw frame (hex)
"""

from __future__ import annotations

import argparse
import logging
import sys

from plasma_sony_headphones.device import Headphones
from plasma_sony_headphones.transport import discovery


def _list() -> int:
    devices = discovery.scan()
    if not devices:
        print("No recognised Sony headsets found. Pair one via bluetoothctl first.")
        return 1
    print("Recognised Sony headsets:")
    for d in devices:
        flag = "svc" if d.has_service else "name-match"
        print(f"  {d.mac}  {d.name:24}  [{flag}, {'connected' if d.connected else 'paired'}]")
    print("\nRun:  python cli.py <MAC>   to dump the handshake.")
    return 0


def _dump(mac: str) -> int:
    hp = Headphones(mac)
    print(f"Connecting to {mac} ...")
    hp.connect()
    print("Running handshake ...\n")
    st = hp.handshake()

    print("=== Device ===")
    print(f"  Model         : {st.model_name}")
    print(f"  Model ID      : {st.model_id}")
    print(f"  Serial number : {st.serial}")
    print(f"  Device ID     : {st.device_id}")
    print(f"  Version fields: {'.'.join(str(v) for v in st.version_fields)}")
    print(f"  Protocol info : {st.protocol_raw.hex(' ')}")
    print(f"  Identifiers   : {st.identifiers}")
    print("\n=== Initial state ===")
    print(f"  Battery : {st.battery}")
    print(f"  NC/ASM  : {st.ncasm}")
    hp.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mac", nargs="?", help="headset MAC (omit to scan)")
    parser.add_argument("--raw", action="store_true", help="verbose frame logging")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if (args.verbose or args.raw) else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.mac:
        return _list()
    try:
        return _dump(args.mac)
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
