"""Packet wire format for NetSim.

Every packet that travels through a channel is serialized to bytes using a
simple binary layout::

    ┌──────────┬──────────┬──────────────┬──────────────────────────────┐
    │  src (4) │  dst (4) │ checksum (4) │  type_byte (1) + payload (N) │
    └──────────┴──────────┴──────────────┴──────────────────────────────┘
    All multi-byte fields are in network (big-endian) byte order.

The *checksum* is a CRC-32 computed over ``src || dst || type_byte || payload``
and stored in the header.  The channel verifies this checksum before delivery;
corrupted packets are silently dropped and counted as channel drops.

The *type_byte* distinguishes ``bytes`` payloads (``0x00``) from UTF-8 ``str``
payloads (``0x01``), allowing the original Python type to be recovered on
deserialization.

Public API
----------
* :class:`Packet`          — immutable dataclass holding ``(data, src, dst)``.
* :func:`encode_packet`    — serialize a :class:`Packet` to bytes.
* :func:`decode_packet`    — deserialize bytes back to a :class:`Packet`.
* :func:`validate`         — verify the CRC-32 checksum of a raw packet.
* :func:`packet_length`    — byte length of the serialized form.
* :func:`get_checksum`     — extract the checksum field from raw bytes.
* :func:`strip_checksum`   — return raw bytes with the checksum field zeroed.
"""
import struct
import zlib
from dataclasses import dataclass

HEADER_FORMAT = "!III"
HEADER_STRUCT = struct.Struct(HEADER_FORMAT)
HEADER_LEN = HEADER_STRUCT.size        # 12 bytes: src (4) + dst (4) + checksum (4)
MIN_PACKET_LEN = HEADER_LEN + 1        # header + at least the payload type byte
UINT32_MAX = 0xFFFFFFFF

# Payload type markers stored as the first byte of the encoded payload.
PAYLOAD_TYPE_BYTES = 0
PAYLOAD_TYPE_TEXT  = 1


@dataclass(slots=True)
class Packet:
    """A single network packet.

    Attributes:
        data: The application payload.  Either raw :class:`bytes` or a UTF-8
              :class:`str`; the type is preserved through serialization.
        src:  Source node identifier (uint32).
        dst:  Destination node identifier (uint32).
              Use ``BROADCAST_ID = 0xFFFFFFFF`` for layer-2 broadcast.
    """
    data: bytes | str
    src:  int
    dst:  int

    def __repr__(self) -> str:
        payload_repr = (
            f"{len(self.data)}B" if isinstance(self.data, bytes) else repr(self.data[:40])
        )
        return f"Packet(src={self.src}, dst={self.dst}, data={payload_repr})"


def _validate_uint32(value: int, name: str) -> None:
    """Raise if *value* is not a valid uint32 integer."""
    if not isinstance(value, int):
        raise TypeError(f"Packet {name} must be an integer")
    if not 0 <= value <= UINT32_MAX:
        raise ValueError(f"Packet {name} must be in range [0, {UINT32_MAX}]")


def _encode_payload(data: bytes | str) -> bytes:
    """Prepend the payload type byte and encode to bytes."""
    if isinstance(data, bytes):
        return bytes([PAYLOAD_TYPE_BYTES]) + data
    if isinstance(data, str):
        return bytes([PAYLOAD_TYPE_TEXT]) + data.encode("utf-8")
    raise TypeError("Packet data must be bytes or str")


def _decode_payload(payload: bytes) -> bytes | str:
    """Strip the type byte and decode the payload back to its original type."""
    if len(payload) == 0:
        raise ValueError("Packet payload is missing type marker")

    payload_type = payload[0]
    payload_bytes = payload[1:]
    if payload_type == PAYLOAD_TYPE_BYTES:
        return payload_bytes
    if payload_type == PAYLOAD_TYPE_TEXT:
        return payload_bytes.decode("utf-8")
    raise ValueError(f"Unsupported payload type: {payload_type}")


def encode_packet(packet: Packet) -> bytes:
    """Serialize *packet* to a byte string.

    Wire layout: ``src (4B) | dst (4B) | crc32 (4B) | type_byte (1B) | payload``
    The CRC-32 is computed over ``src || dst || type_byte || payload``.

    Raises:
        TypeError:  If ``src`` or ``dst`` are not integers, or ``data`` is
                    neither ``bytes`` nor ``str``.
        ValueError: If ``src`` or ``dst`` are outside the uint32 range.
    """
    _validate_uint32(packet.src, "src")
    _validate_uint32(packet.dst, "dst")

    encoded_payload = _encode_payload(packet.data)
    src_dst = struct.pack("!II", packet.src, packet.dst)
    checksum = zlib.crc32(src_dst + encoded_payload) & UINT32_MAX
    return HEADER_STRUCT.pack(packet.src, packet.dst, checksum) + encoded_payload


def decode_packet(data: bytes, *, validate_checksum: bool = True) -> Packet:
    """Deserialize raw bytes back to a :class:`Packet`.

    Args:
        data:              Raw bytes as produced by :func:`encode_packet`.
        validate_checksum: When ``True`` (the default), verifies the CRC-32
                           before decoding.  Pass ``False`` only if the channel
                           has already validated the checksum.

    Raises:
        ValueError: If *data* is too short, or if the checksum is invalid.
    """
    if len(data) < MIN_PACKET_LEN:
        raise ValueError("Packet data too short for header")

    src, dst, _ = HEADER_STRUCT.unpack(data[:HEADER_LEN])
    if validate_checksum and not validate(data):
        raise ValueError("Packet checksum validation failed")

    payload = data[HEADER_LEN:]
    return Packet(_decode_payload(payload), src, dst)


def validate(data: bytes) -> bool:
    """Return ``True`` if the CRC-32 checksum in *data* is correct.

    Returns ``False`` (rather than raising) for packets that are too short or
    whose checksum doesn't match, so callers can treat all failures uniformly.
    """
    if len(data) < MIN_PACKET_LEN:
        return False

    src, dst, checksum = HEADER_STRUCT.unpack(data[:HEADER_LEN])
    if not 0 <= src <= UINT32_MAX or not 0 <= dst <= UINT32_MAX:
        return False

    payload = data[HEADER_LEN:]
    computed = zlib.crc32(struct.pack("!II", src, dst) + payload) & UINT32_MAX
    return computed == checksum


def get_checksum(data: bytes) -> int:
    """Extract the CRC-32 checksum field from raw packet bytes.

    Raises:
        ValueError: If *data* is shorter than the header.
    """
    if len(data) < HEADER_LEN:
        raise ValueError("Packet too short for checksum")
    return HEADER_STRUCT.unpack(data[:HEADER_LEN])[2]


def strip_checksum(data: bytes) -> bytes:
    """Return *data* with the checksum field replaced by zeros.

    Useful for testing or comparison when you want to ignore the checksum.

    Raises:
        ValueError: If *data* is shorter than the header.
    """
    if len(data) < HEADER_LEN:
        raise ValueError("Packet too short")

    src, dst, _ = HEADER_STRUCT.unpack(data[:HEADER_LEN])
    return struct.pack("!II", src, dst) + data[HEADER_LEN:]


def packet_length(packet: Packet) -> int:
    """Return the byte length of *packet* in its serialized (wire) form.

    This is the length that the channel uses when computing transmission time
    from the configured bit rate.
    """
    # HEADER_LEN bytes for src/dst/checksum + 1 byte for the type marker +
    # the payload itself.
    return HEADER_LEN + 1 + (
        len(packet.data) if isinstance(packet.data, bytes) else len(str(packet.data).encode("utf-8"))
    )