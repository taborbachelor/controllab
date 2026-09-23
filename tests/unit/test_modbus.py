"""The Modbus PDU/ADU layer on raw bytes, no sockets. Where the Modbus
Application Protocol spec (v1.1b3, section 6) gives a worked example, the
test uses that example's exact bytes -- so these check conformance to the
spec, not just agreement with this implementation."""
import struct

import pytest

from services.protocols.modbus import (
    ILLEGAL_DATA_ADDRESS,
    ILLEGAL_DATA_VALUE,
    ILLEGAL_FUNCTION,
    SERVER_DEVICE_FAILURE,
    MemoryDataStore,
    handle_adu,
    handle_pdu,
    pack_bits,
    unpack_bits,
)


def store() -> MemoryDataStore:
    return MemoryDataStore(coils=40, discrete_inputs=40, holding_registers=20, input_registers=20)


def test_read_coils_matches_the_spec_example():
    # Spec 6.1: read 19 coils from 20 (address 0x13); coils 27-20 = 0xCD, 35-28 = 0x6B, 38-36 = 0x05.
    s = store()
    s.coils[19:38] = unpack_bits(bytes.fromhex("CD6B05"), 19)
    assert handle_pdu(s, bytes.fromhex("0100130013")) == bytes.fromhex("0103CD6B05")


def test_read_discrete_inputs_uses_its_own_table():
    s = store()
    s.discrete_inputs[0] = True
    assert handle_pdu(s, bytes.fromhex("0200000008")) == bytes.fromhex("020101")
    assert handle_pdu(s, bytes.fromhex("0100000008")) == bytes.fromhex("010100")


def test_read_holding_registers_matches_the_spec_example():
    # Spec 6.3: registers 108-110 (addresses 0x6B..0x6D) = 0x022B, 0x0000, 0x0064.
    s = MemoryDataStore(holding_registers=120)
    s.holding_registers[0x6B:0x6E] = [0x022B, 0x0000, 0x0064]
    assert handle_pdu(s, bytes.fromhex("03006B0003")) == bytes.fromhex("0306022B00000064")


def test_read_input_registers():
    s = store()
    s.input_registers[8] = 0x000A
    assert handle_pdu(s, bytes.fromhex("0400080001")) == bytes.fromhex("0402000A")


def test_write_single_coil_echoes_the_request():
    s = store()
    assert handle_pdu(s, bytes.fromhex("050000FF00")) == bytes.fromhex("050000FF00")
    assert s.coils[0] is True
    assert handle_pdu(s, bytes.fromhex("0500000000")) == bytes.fromhex("0500000000")
    assert s.coils[0] is False


def test_write_single_coil_rejects_anything_but_ff00_or_0000():
    assert handle_pdu(store(), bytes.fromhex("0500000001")) == bytes((0x85, ILLEGAL_DATA_VALUE))


def test_write_single_register_matches_the_spec_example():
    s = MemoryDataStore(holding_registers=5)
    assert handle_pdu(s, bytes.fromhex("0600010003")) == bytes.fromhex("0600010003")
    assert s.holding_registers[1] == 3


def test_write_multiple_coils_matches_the_spec_example():
    # Spec 6.11: 10 coils from 20 (address 0x13), data CD 01.
    s = store()
    assert handle_pdu(s, bytes.fromhex("0F0013000A02CD01")) == bytes.fromhex("0F0013000A")
    assert s.coils[19:29] == unpack_bits(bytes.fromhex("CD01"), 10)


def test_write_multiple_registers_matches_the_spec_example():
    # Spec 6.12: 2 registers from 2 (address 1), values 0x000A, 0x0102.
    s = MemoryDataStore(holding_registers=5)
    assert handle_pdu(s, bytes.fromhex("100001000204000A0102")) == bytes.fromhex("1000010002")
    assert s.holding_registers[1:3] == [0x000A, 0x0102]


@pytest.mark.parametrize(
    "request_hex,code",
    [
        ("2B0E0100", ILLEGAL_FUNCTION),  # read device identification: not implemented
        ("0100270002", ILLEGAL_DATA_ADDRESS),  # coils 39..40, table ends at 39
        ("03FFFF0001", ILLEGAL_DATA_ADDRESS),
        ("0100000000", ILLEGAL_DATA_VALUE),  # quantity 0
        ("01000007D1", ILLEGAL_DATA_VALUE),  # 2001 bits > 2000
        ("030000007E", ILLEGAL_DATA_VALUE),  # 126 registers > 125
        ("0F0000000A01CD", ILLEGAL_DATA_VALUE),  # 10 coils need 2 bytes, got 1
        ("10000000020400", ILLEGAL_DATA_VALUE),  # byte count says 4, 1 byte present
        ("0300", ILLEGAL_DATA_VALUE),  # truncated
        ("030000000100", ILLEGAL_DATA_VALUE),  # trailing garbage
    ],
)
def test_exception_responses(request_hex, code):
    pdu = bytes.fromhex(request_hex)
    assert handle_pdu(store(), pdu) == bytes((pdu[0] | 0x80, code))


def test_a_store_bug_is_a_device_failure_not_a_blamed_request():
    class Broken(MemoryDataStore):
        def read_holding_registers(self, address, count):
            return [70_000]  # can't be packed into 16 bits: a server-side fault

    assert handle_pdu(Broken(holding_registers=1), bytes.fromhex("0300000001")) == bytes((0x83, SERVER_DEVICE_FAILURE))


def test_failed_write_leaves_the_table_untouched():
    s = store()
    handle_pdu(s, bytes.fromhex("0F002600030107"))  # coils 38..40: runs off the end
    assert s.coils == [False] * 40


def test_bit_packing_round_trips():
    bits = [True, False, True, True, False, False, False, False, True]
    assert pack_bits(bits) == bytes((0b00001101, 0b00000001))
    assert unpack_bits(pack_bits(bits), len(bits)) == bits


def test_adu_echoes_transaction_and_unit_and_sets_length():
    s = store()
    s.input_registers[0] = 7
    frame = struct.pack(">HHHB", 0x1234, 0, 6, 0x11) + bytes.fromhex("0400000001")
    assert handle_adu(s, frame) == struct.pack(">HHHB", 0x1234, 0, 5, 0x11) + bytes.fromhex("04020007")


@pytest.mark.parametrize(
    "frame",
    [
        struct.pack(">HHHB", 1, 1, 6, 1) + bytes.fromhex("0400000001"),  # protocol id != 0
        struct.pack(">HHHB", 1, 0, 9, 1) + bytes.fromhex("0400000001"),  # length disagrees
        b"\x00\x01\x00",  # shorter than a header
    ],
)
def test_adu_discards_non_modbus_frames(frame):
    assert handle_adu(store(), frame) is None
