import struct
import zlib
from dataclasses import dataclass
from typing import Any

HEADER_FORMAT = "!IIBI"


@dataclass
class Packet:
    def __init__(self, data: Any, src: int, dst: int):
        self.src = src
        self.dst = dst
        self.data = data
        self.checksum: int | None = None

    def to_bytes(self) -> bytes:
        if self.src < 0 or self.dst < 0:
            raise ValueError("Packet src and dst must be non-negative integers")

        if isinstance(self.data, bytes):
            payload_type = 0
            payload_bytes = self.data
        else:
            payload_type = 1
            payload_bytes = str(self.data).encode("utf-8")

        # header: src(4), dst(4), payload_type(1), payload_len(4)
        header = struct.pack(HEADER_FORMAT, self.src, self.dst, payload_type, len(payload_bytes))
        body = header + payload_bytes
        checksum = zlib.crc32(body) & 0xFFFFFFFF
        self.checksum = checksum
        return body + struct.pack("!I", checksum)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Packet":
        header_size = struct.calcsize(HEADER_FORMAT)
        checksum_size = struct.calcsize("!I")
        if len(data) < header_size + checksum_size:
            raise ValueError("Packet data too short for header")

        src, dst, payload_type, payload_len = struct.unpack(HEADER_FORMAT, data[:header_size])
        expected_len = header_size + payload_len + checksum_size
        if len(data) != expected_len:
            raise ValueError("Packet data length does not match encoded lengths")

        offset = header_size
        payload_bytes = data[offset:offset + payload_len]
        offset += payload_len
        checksum = struct.unpack("!I", data[offset:offset + checksum_size])[0]

        if payload_type == 0:
            payload: Any = payload_bytes
        elif payload_type == 1:
            payload = payload_bytes.decode("utf-8")
        else:
            raise ValueError(f"Unsupported payload type: {payload_type}")

        packet = cls(payload, src, dst)
        packet.checksum = checksum
        return packet

    def validate(self) -> bool:
        if self.checksum is None:
            return False

        if self.src < 0 or self.dst < 0:
            return False

        if isinstance(self.data, bytes):
            payload_type = 0
            payload_bytes = self.data
        else:
            payload_type = 1
            payload_bytes = str(self.data).encode("utf-8")

        header = struct.pack(HEADER_FORMAT, self.src, self.dst, payload_type, len(payload_bytes))
        body = header + payload_bytes
        computed_checksum = zlib.crc32(body) & 0xFFFFFFFF
        return computed_checksum == self.checksum
    
    def __len__(self):
        return len(self.to_bytes())
    
