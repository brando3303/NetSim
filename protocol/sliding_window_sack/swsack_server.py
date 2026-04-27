from __future__ import annotations

from dataclasses import dataclass

from src.node import Node
from src.packet import Packet, packet_length

from .common import SackBlock, decode_sack_payload, encode_sw_payload


@dataclass(slots=True)
class _WindowEntry:
	acked: bool
	packet: Packet


class SWSACKServer(Node):
	def __init__(
		self,
		name: int,
		receiver: int,
		data: bytes | str,
		*,
		window_size: int,
		frame_size: int,
		retransmit_timeout: int,
		seq_space: int = 256,
	):
		super().__init__(name)
		if window_size <= 0:
			raise ValueError("window_size must be > 0")
		if seq_space <= 2:
			raise ValueError("seq_space must be > 2")
		if window_size >= seq_space // 2:
			raise ValueError("window_size must be less than half of seq_space")
		if frame_size <= 0:
			raise ValueError("frame_size must be > 0")
		if retransmit_timeout <= 0:
			raise ValueError("retransmit_timeout must be > 0")

		self.seq_space = seq_space
		self.window_size = window_size
		self.window: dict[int, _WindowEntry] = {}

		self.last_ack_received = 0
		self.last_frame_sent = 0

		self.receiver = receiver
		self.data = data.encode("utf-8") if isinstance(data, str) else bytes(data)
		self.data_index = 0
		self.frame_size = frame_size
		self.retransmit_timeout = retransmit_timeout

	def init(self):
		return None

	def start(self):
		for _ in range(self.window_size):
			next_chunk = self.next_data()
			if len(next_chunk) == 0:
				break
			next_seq = (self.last_frame_sent + 1) % self.seq_space
			self.send_frame(next_seq, next_chunk)
			self.last_frame_sent = next_seq

	def receive(self, packet: Packet):
		if packet.src != self.receiver:
			return

		decoded = decode_sack_payload(packet.data)
		if decoded is None:
			return

		ack_seq, sack_blocks = decoded
		print(f"Server received ACK for seq_num={ack_seq} with SACK blocks={sack_blocks}")
		self.handle_ack_packet(ack_seq, sack_blocks)

	def handle_ack_packet(self, ack_seq: int, sack_blocks: list[SackBlock]):
		if not self.is_in_window(ack_seq):
			return

		self.process_ack(ack_seq)
		for sack_block in sack_blocks:
			self.process_sack_block(sack_block)

		self.update_window()

		if len(sack_blocks) > 0:
			self.retransmit_next_block()

	def process_ack(self, ack_seq: int):
		# if ack_seq > self.last_ack_received:
		# TODO fix this...
		self.ack_block((self.last_ack_received + 1) % self.seq_space, ack_seq)
		entry = self.window.get(ack_seq)
		if entry is None:
			return
		entry.acked = True

	def process_sack_block(self, sack_block: SackBlock):
		self.ack_block(sack_block.sle, sack_block.sre)

	def update_window(self):
		while True:
			next_seq = (self.last_ack_received + 1) % self.seq_space
			entry = self.window.get(next_seq)
			if entry is None or not entry.acked:
				break

			self.last_ack_received = next_seq
			print(f"Server slid window to LAS={self.last_ack_received}")
			del self.window[next_seq]

			next_chunk = self.next_data()
			if len(next_chunk) == 0:
				continue

			send_seq = (self.last_frame_sent + 1) % self.seq_space
			self.send_frame(send_seq, next_chunk)
			self.last_frame_sent = send_seq

	def next_data(self) -> bytes:
		remaining = len(self.data) - self.data_index
		if remaining <= 0:
			return b""

		payload_len = min(remaining, self.frame_size)
		next_chunk = self.data[self.data_index : self.data_index + payload_len]
		self.data_index += payload_len
		return next_chunk

	def send_frame(self, seq_num: int, payload: bytes):
		print(f"Server sending packet with seq_num={seq_num}, payload={payload}")
		packet = Packet(
			data=encode_sw_payload(seq_num, payload),
			src=self.name,
			dst=self.receiver,
		)
		print(f"packet size: {packet_length(packet)} bytes")
		self.channels[0].send(packet)
		self.set_timer(self.retransmit_timeout, self.retransmit_timer, seq_num)

		if seq_num not in self.window:
			self.window[seq_num] = _WindowEntry(acked=False, packet=packet)

	def retransmit_timer(self, seq_num: int):
		if not self.is_in_window(seq_num):
			return

		entry = self.window.get(seq_num)
		if entry is None or entry.acked:
			return

		self.channels[0].send(entry.packet)
		self.set_timer(self.retransmit_timeout, self.retransmit_timer, seq_num)

	def is_in_window(self, seq_num: int) -> bool:
		return 0 < self.seq_dist(self.last_ack_received, seq_num) <= self.window_size

	def seq_dist(self, left: int, right: int) -> int:
		return (right - left) % self.seq_space

	def ack_block(self, sle: int, sre: int):
		if self.seq_dist(sle, sre) > self.seq_space // 2:
			return
		i = sle % self.seq_space
		while i != sre % self.seq_space:
			if self.is_in_window(i):
				entry = self.window.get(i)
				if entry is not None:
					entry.acked = True
			i = (i + 1) % self.seq_space

	def retransmit_next_block(self):
		start = (self.last_ack_received + 1) % self.seq_space
		end = (self.last_frame_sent + 1) % self.seq_space

		if start == end:
			return

		i = start
		entry = self.window.get(i)
		in_unacked_block = entry is not None and not entry.acked

		while in_unacked_block and i != end:
			current = self.window.get(i)
			if current is None or current.acked:
				break

			self.channels[0].send(current.packet)
			self.set_timer(self.retransmit_timeout, self.retransmit_timer, i)

			i = (i + 1) % self.seq_space
			if not self.is_in_window(i):
				break
			next_entry = self.window.get(i)
			in_unacked_block = next_entry is not None and not next_entry.acked

	def is_complete(self) -> bool:
		return self.data_index >= len(self.data) and len(self.window) == 0
