from __future__ import annotations

from src.node import Node
from src.packet import Packet

from .common import SackBlock, decode_sw_payload, encode_sack_payload


class SWSACKClient(Node):
	def __init__(
		self,
		name: int,
		server: int,
		*,
		buffer_window_size: int,
		seq_space: int = 256,
		max_sack_blocks: int = 4,
	):
		super().__init__(name)
		if buffer_window_size <= 0:
			raise ValueError("buffer_window_size must be > 0")
		if seq_space <= 2:
			raise ValueError("seq_space must be > 2")
		if buffer_window_size >= seq_space // 2:
			raise ValueError("buffer_window_size must be less than half of seq_space")
		if max_sack_blocks <= 0:
			raise ValueError("max_sack_blocks must be > 0")

		self.buffer_window_size = buffer_window_size
		self.server = server
		self.buffer: dict[int, bytes] = {}
		self.last_ack_sent = 0
		self.received_data = bytearray()
		self.seq_space = seq_space
		self.max_sack_blocks = max_sack_blocks

	def init(self):
		return None

	def start(self):
		return None

	def receive(self, packet: Packet):
		if packet.src != self.server:
			return

		decoded = decode_sw_payload(packet.data)
		if decoded is None:
			return

		seq_num, payload = decoded
		self.handle_sw_packet(seq_num, payload)

	def handle_sw_packet(self, seq_num: int, payload: bytes):
		print(f"Client received packet with seq_num={seq_num}, payload={payload}, LAS={self.last_ack_sent}")
		if not self.is_in_window(seq_num):
			self.send_sack(self.last_ack_sent, [])
			return

		if seq_num not in self.buffer:
			self.buffer[seq_num] = payload

		self.update_window()
		self.send_sack(self.last_ack_sent, self.generate_sack_blocks())

	def is_in_window(self, seq_num: int) -> bool:
		return 0 < ((seq_num - self.last_ack_sent) % self.seq_space) <= self.buffer_window_size

	def send_sack(self, seq_num: int, sack_blocks: list[SackBlock]):
		ack_packet = Packet(
			data=encode_sack_payload(seq_num, sack_blocks),
			src=self.name,
			dst=self.server,
		)
		self.channels[0].send(ack_packet)

	def update_window(self):
		while True:
			next_seq = (self.last_ack_sent + 1) % self.seq_space
			payload = self.buffer.get(next_seq)
			if payload is None:
				break
			print(f"Client buffer  slid to LAS={next_seq}")
			self.last_ack_sent = next_seq
			self.received_data.extend(payload)
			del self.buffer[next_seq]

	def generate_sack_blocks(self) -> list[SackBlock]:
		i = (self.last_ack_sent + 1) % self.seq_space
		blocks: list[SackBlock] = []

		in_block = False
		sle = 0

		while self.is_in_window(i) and len(blocks) < self.max_sack_blocks:
			if not in_block and i in self.buffer:
				in_block = True
				sle = i

			if in_block and i not in self.buffer:
				in_block = False
				blocks.append(SackBlock(sle=sle, sre=i))

			i = (i + 1) % self.seq_space

		if in_block and len(blocks) < self.max_sack_blocks:
			blocks.append(SackBlock(sle=sle, sre=i))

		return blocks
