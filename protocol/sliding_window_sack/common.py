from __future__ import annotations

import struct
from dataclasses import dataclass

_MAGIC = b"SWSK"
_DATA_TYPE = 1
_ACK_TYPE = 2

_HEADER_STRUCT = struct.Struct("!4sBI")
_ACK_HEADER_STRUCT = struct.Struct("!B")
_BLOCK_STRUCT = struct.Struct("!II")


@dataclass(frozen=True, slots=True)
class SackBlock:
    sle: int
    sre: int


def _to_bytes(data: bytes | str) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    raise TypeError("Packet payload must be bytes or str")


def encode_sw_payload(seq_num: int, payload: bytes) -> bytes:
    return _HEADER_STRUCT.pack(_MAGIC, _DATA_TYPE, seq_num) + payload


def decode_sw_payload(data: bytes | str) -> tuple[int, bytes] | None:
    payload = _to_bytes(data)
    if len(payload) < _HEADER_STRUCT.size:
        return None

    magic, packet_type, seq_num = _HEADER_STRUCT.unpack(payload[: _HEADER_STRUCT.size])
    if magic != _MAGIC or packet_type != _DATA_TYPE:
        return None

    return seq_num, payload[_HEADER_STRUCT.size :]


def encode_sack_payload(ack_seq_num: int, sack_blocks: list[SackBlock]) -> bytes:
    block_count = min(255, len(sack_blocks))
    encoded = bytearray(_HEADER_STRUCT.pack(_MAGIC, _ACK_TYPE, ack_seq_num))
    encoded.extend(_ACK_HEADER_STRUCT.pack(block_count))
    for block in sack_blocks[:block_count]:
        encoded.extend(_BLOCK_STRUCT.pack(block.sle, block.sre))
    return bytes(encoded)


def decode_sack_payload(data: bytes | str) -> tuple[int, list[SackBlock]] | None:
    payload = _to_bytes(data)
    minimum_len = _HEADER_STRUCT.size + _ACK_HEADER_STRUCT.size
    if len(payload) < minimum_len:
        return None

    magic, packet_type, ack_seq_num = _HEADER_STRUCT.unpack(payload[: _HEADER_STRUCT.size])
    if magic != _MAGIC or packet_type != _ACK_TYPE:
        return None

    (block_count,) = _ACK_HEADER_STRUCT.unpack(payload[_HEADER_STRUCT.size : minimum_len])

    blocks_start = minimum_len
    blocks_len = len(payload) - blocks_start
    if blocks_len < block_count * _BLOCK_STRUCT.size:
        return None

    blocks: list[SackBlock] = []
    offset = blocks_start
    for _ in range(block_count):
        sle, sre = _BLOCK_STRUCT.unpack(payload[offset : offset + _BLOCK_STRUCT.size])
        blocks.append(SackBlock(sle=sle, sre=sre))
        offset += _BLOCK_STRUCT.size

    return ack_seq_num, blocks
