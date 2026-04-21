import struct
import zlib
from dataclasses import dataclass

HEADER_FORMAT = "!III"
HEADER_STRUCT = struct.Struct(HEADER_FORMAT)
HEADER_LEN = HEADER_STRUCT.size
MIN_PACKET_LEN = HEADER_LEN + 1
UINT32_MAX = 0xFFFFFFFF

PAYLOAD_TYPE_BYTES = 0
PAYLOAD_TYPE_TEXT = 1


@dataclass(slots=True)
class Packet:
    data: bytes | str
    src: int
    dst: int


def _validate_uint32(value: int, name: str) -> None:
    if not isinstance(value, int):
        raise TypeError(f"Packet {name} must be an integer")
    if not 0 <= value <= UINT32_MAX:
        raise ValueError(f"Packet {name} must be in range [0, {UINT32_MAX}]")


def _encode_payload(data: bytes | str) -> bytes:
    if isinstance(data, bytes):
        return bytes([PAYLOAD_TYPE_BYTES]) + data
    if isinstance(data, str):
        return bytes([PAYLOAD_TYPE_TEXT]) + data.encode("utf-8")
    raise TypeError("Packet data must be bytes or str")


def _decode_payload(payload: bytes) -> bytes | str:
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
    _validate_uint32(packet.src, "src")
    _validate_uint32(packet.dst, "dst")

    encoded_payload = _encode_payload(packet.data)
    src_dst = struct.pack("!II", packet.src, packet.dst)
    checksum = zlib.crc32(src_dst + encoded_payload) & UINT32_MAX
    return HEADER_STRUCT.pack(packet.src, packet.dst, checksum) + encoded_payload


def decode_packet(data: bytes, *, validate_checksum: bool = True) -> Packet:
    if len(data) < MIN_PACKET_LEN:
        raise ValueError("Packet data too short for header")

    src, dst, _ = HEADER_STRUCT.unpack(data[:HEADER_LEN])
    if validate_checksum and not validate(data):
        raise ValueError("Packet checksum validation failed")

    payload = data[HEADER_LEN:]
    return Packet(_decode_payload(payload), src, dst)


def validate(data: bytes) -> bool:
    if len(data) < MIN_PACKET_LEN:
        return False

    src, dst, checksum = HEADER_STRUCT.unpack(data[:HEADER_LEN])
    if not 0 <= src <= UINT32_MAX or not 0 <= dst <= UINT32_MAX:
        return False

    payload = data[HEADER_LEN:]
    computed = zlib.crc32(struct.pack("!II", src, dst) + payload) & UINT32_MAX
    return computed == checksum


def get_checksum(data: bytes) -> int:
    if len(data) < HEADER_LEN:
        raise ValueError("Packet too short for checksum")
    return HEADER_STRUCT.unpack(data[:HEADER_LEN])[2]


def strip_checksum(data: bytes) -> bytes:
    if len(data) < HEADER_LEN:
        raise ValueError("Packet too short")

    src, dst, _ = HEADER_STRUCT.unpack(data[:HEADER_LEN])
    return struct.pack("!II", src, dst) + data[HEADER_LEN:]