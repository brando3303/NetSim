"""Sliding-window SACK wire-format codec.

Defines the on-the-wire encoding for two message types that are carried inside
the :class:`~src.packet.Packet` payload field:

``DATA`` frame
    Sent by the server.  Layout: ``MAGIC (4B) | DATA_TYPE (1B) | seq_num (4B) | payload``

``ACK`` frame
    Sent by the client.  Layout: ``MAGIC (4B) | ACK_TYPE (1B) | ack_seq_num (4B)
    | block_count (1B) | [sle (4B) | sre (4B)] * block_count``

The magic bytes ``b"SWSK"`` guard against accidentally decoding an unrelated
payload with the wrong decoder.

SACK block semantics
--------------------
A :class:`SackBlock` describes a *contiguous run of buffered-but-not-yet-
delivered sequence numbers* as a half-open interval ``[sle, sre)``.
Here *sle* is the sequence-left-edge (first buffered seq) and *sre* is the
sequence-right-edge (first sequence number after the block).
Sequence numbers wrap around at ``seq_space`` (modular arithmetic).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

_MAGIC = b"SWSK"
_DATA_TYPE = 1
_ACK_TYPE  = 2

# Header shared by both frame types: 4 bytes magic + 1 byte type + 4 bytes seq.
_HEADER_STRUCT     = struct.Struct("!4sBI")
# Count of SACK blocks (1 byte, max 255).
_ACK_HEADER_STRUCT = struct.Struct("!B")
# Each SACK block: sle (4B) + sre (4B).
_BLOCK_STRUCT      = struct.Struct("!II")


@dataclass(frozen=True, slots=True)
class SackBlock:
    """A single Selective ACK block.

    Describes a half-open interval ``[sle, sre)`` of sequence numbers that
    have been received out-of-order and are buffered at the receiver.
    Both values are modular (wrap at ``seq_space``).

    Attributes:
        sle: Sequence left edge  — first buffered (out-of-order) sequence number.
        sre: Sequence right edge — first sequence number *after* this block.
    """
    sle: int
    sre: int


def _to_bytes(data: bytes | str) -> bytes:
    """Coerce *data* to bytes, encoding str as UTF-8."""
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    raise TypeError("Packet payload must be bytes or str")


def encode_sw_payload(seq_num: int, payload: bytes) -> bytes:
    """Encode a DATA frame payload.

    Args:
        seq_num: Sequence number of this data frame (uint32).
        payload: Application data bytes.

    Returns:
        Bytes suitable for use as the ``data`` field of a
        :class:`~src.packet.Packet`.
    """
    return _HEADER_STRUCT.pack(_MAGIC, _DATA_TYPE, seq_num) + payload


def decode_sw_payload(data: bytes | str) -> tuple[int, bytes] | None:
    """Decode a DATA frame payload.

    Returns:
        ``(seq_num, payload_bytes)`` on success, or ``None`` if *data* is too
        short or does not start with the expected magic/type.
    """
    payload = _to_bytes(data)
    if len(payload) < _HEADER_STRUCT.size:
        return None

    magic, packet_type, seq_num = _HEADER_STRUCT.unpack(payload[: _HEADER_STRUCT.size])
    if magic != _MAGIC or packet_type != _DATA_TYPE:
        return None

    return seq_num, payload[_HEADER_STRUCT.size :]


def encode_sack_payload(ack_seq_num: int, sack_blocks: list[SackBlock]) -> bytes:
    """Encode an ACK frame payload (cumulative ACK + optional SACK blocks).

    Args:
        ack_seq_num:  Cumulative acknowledgment sequence number.
        sack_blocks:  Up to 255 :class:`SackBlock` instances describing
                      out-of-order buffered ranges.

    Returns:
        Bytes suitable for use as the ``data`` field of a
        :class:`~src.packet.Packet`.
    """
    block_count = min(255, len(sack_blocks))
    encoded = bytearray(_HEADER_STRUCT.pack(_MAGIC, _ACK_TYPE, ack_seq_num))
    encoded.extend(_ACK_HEADER_STRUCT.pack(block_count))
    for block in sack_blocks[:block_count]:
        encoded.extend(_BLOCK_STRUCT.pack(block.sle, block.sre))
    return bytes(encoded)


def decode_sack_payload(data: bytes | str) -> tuple[int, list[SackBlock]] | None:
    """Decode an ACK frame payload.

    Returns:
        ``(ack_seq_num, sack_blocks)`` on success, or ``None`` if *data* is
        malformed (too short, wrong magic, or truncated block list).
    """
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
