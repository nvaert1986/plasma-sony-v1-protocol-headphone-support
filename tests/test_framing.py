"""Unit tests for the MDR frame layer — the crown-jewel module.

Run with:  python -m pytest   (or: python -m unittest)
"""

from __future__ import annotations

import unittest

from plasma_sony_headphones.protocol import framing, messages
from plasma_sony_headphones.protocol.enums import DataType


class TestFraming(unittest.TestCase):
    def test_roundtrip_simple(self):
        payload = b"\x00\x01\x02\x03"
        raw = framing.encode(payload, DataType.DATA_MDR, 0)
        self.assertEqual(raw[0], framing.START_MARKER)
        self.assertEqual(raw[-1], framing.END_MARKER)
        frame = framing.decode(raw[1:-1])
        self.assertEqual(frame.data_type, DataType.DATA_MDR)
        self.assertEqual(frame.seq, 0)
        self.assertEqual(frame.payload, payload)

    def test_checksum_is_sum_mod_256(self):
        raw = framing.encode(b"\x10\x20", DataType.DATA_MDR, 1)
        body = framing._unescape(raw[1:-1])
        self.assertEqual(body[-1], sum(body[:-1]) & 0xFF)

    def test_escaping_of_marker_bytes(self):
        # payload containing 0x3C, 0x3D, 0x3E must not break framing
        payload = bytes([0x3C, 0x3D, 0x3E, 0x00, 0x3E])
        raw = framing.encode(payload, DataType.DATA_MDR, 0)
        # markers only at the very ends
        self.assertNotIn(framing.START_MARKER, raw[1:-1])
        self.assertNotIn(framing.END_MARKER, raw[1:-1])
        self.assertEqual(framing.decode(raw[1:-1]).payload, payload)

    def test_bad_checksum_raises(self):
        raw = bytearray(framing.encode(b"\x01\x02", DataType.DATA_MDR, 0))
        # corrupt a payload byte (index 6 inside body, +1 for start marker)
        raw[7] ^= 0xFF
        with self.assertRaises(framing.FrameError):
            framing.decode(bytes(raw[1:-1]))

    def test_reader_reassembles_split_frames(self):
        f1 = framing.encode(b"\xaa", DataType.DATA_MDR, 0)
        f2 = framing.encode(b"\xbb\xcc", DataType.ACK, 1)
        reader = framing.FrameReader()
        stream = f1 + f2
        # feed byte-by-byte to prove reassembly across reads
        frames = []
        for b in stream:
            frames.extend(reader.feed(bytes([b])))
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].payload, b"\xaa")
        self.assertEqual(frames[1].data_type, DataType.ACK)


class TestMessages(unittest.TestCase):
    def test_get_protocol_info_bytes(self):
        self.assertEqual(messages.build_get_protocol_info(), bytes([0x00, 0x00]))

    def test_get_battery_bytes(self):
        self.assertEqual(messages.build_get_battery(), bytes([0x22, 0x00]))

    def test_set_ncasm_ambient_layout(self):
        # Ambient: 0x68 0x02 effect LEVEL_ADJUSTMENT(0x01) NC-OFF(0x00)
        #          LEVEL_ADJUSTMENT(0x01) asmId level
        p = messages.build_set_ncasm(enabled=True, focus_on_voice=True, asm_level=10)
        self.assertEqual(p[0], 0x68)
        self.assertEqual(p[1], 0x02)
        self.assertEqual(p[3], 0x01)   # NcAsmSettingType.LEVEL_ADJUSTMENT
        self.assertEqual(p[4], 0x00)   # NcDualSingleValue.OFF (NC off in ambient)
        self.assertEqual(p[5], 0x01)
        self.assertEqual(p[6], 0x01)   # AsmId.VOICE
        self.assertEqual(p[7], 10)

    def test_set_ncasm_disabled_is_noise_cancelling(self):
        # Unchecking Ambient => Noise Cancelling, NOT effect=OFF. Mirrors the
        # device's own NC state: settingType=DUAL_SINGLE_OFF(0x02), ternary=DUAL,
        # level inert (0).
        p = messages.build_set_ncasm(enabled=False)
        self.assertEqual(p[3], 0x02)   # NcAsmSettingType.DUAL_SINGLE_OFF
        self.assertEqual(p[4], 0x02)   # NcDualSingleValue.DUAL
        self.assertEqual(p[7], 0x00)

    def test_parse_ncasm_distinguishes_nc_from_ambient(self):
        nc = messages.parse_ncasm(bytes.fromhex("6702010202010000"))
        self.assertFalse(nc.enabled)   # NC mode -> ambient off
        amb = messages.parse_ncasm(bytes.fromhex("6702010100010105"))
        self.assertTrue(amb.enabled)   # NC ternary OFF -> ambient on
        self.assertTrue(amb.focus_on_voice)
        self.assertEqual(amb.asm_level, 5)

    def test_parse_battery_single(self):
        b = messages.parse_battery(bytes([0x23, 0x00, 77, 0x01]))
        self.assertEqual(b.level, 77)
        self.assertTrue(b.charging)


if __name__ == "__main__":
    unittest.main()
