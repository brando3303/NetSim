from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.node import Node
from src.packet import Packet

from .common import SackBlock, decode_sack_payload, encode_sw_payload


@dataclass(slots=True)
class _WindowEntry:
  acked: bool
  packet: Packet
  time_sent: int
  retransmitted: bool


class ATServer(Node):
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
		min_rto: int = 20,
		max_rto: int = 2000,
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
		if min_rto <= 0:
			raise ValueError("min_rto must be > 0")
		if max_rto < min_rto:
			raise ValueError("max_rto must be >= min_rto")

		self.seq_space = seq_space
		self.window_size = window_size
		self.window: dict[int, _WindowEntry] = {}

		self.last_ack_received = 0
		self.last_frame_sent = 0

		self.receiver = receiver
		self.data = data.encode("utf-8") if isinstance(data, str) else bytes(data)
		self.data_index = 0
		self.frame_size = frame_size

		self.min_rto = min_rto
		self.max_rto = max_rto
		self.retransmit_timeout = self._clamp_rto(retransmit_timeout)
		self.smoothed_round_trip_time = float(100)
		self.smoothed_variance = float(10)

		self.rto_timer_running = False
		self.fr_num_acks = 0
		self.fr_last_seen_seq = None

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

		self.set_timer(self.retransmit_timeout, self.retransmit_timer)

		

	def receive(self, packet: Packet):
		if packet.src != self.receiver:
			return

		decoded = decode_sack_payload(packet.data)
		if decoded is None:
			return

		ack_seq, sack_blocks = decoded
		self.handle_ack_packet(ack_seq, sack_blocks)

	def handle_ack_packet(self, ack_seq: int, sack_blocks: list[SackBlock]):
		# increase fast retransmit counter even if ACK is correct
		if not self.is_in_window(ack_seq):
			return


		self.process_ack(ack_seq)
		for sack_block in sack_blocks:
			self.process_sack_block(sack_block)

		if self.fr_last_seen_seq == ack_seq:
			self.fr_num_acks += 1
		else:
			self.fr_num_acks = 1
			self.fr_last_seen_seq = ack_seq

		self.update_window()

		if len(sack_blocks) > 0:
			self.retransmit_next_block()

	def process_ack(self, ack_seq: int):
		entry = self.window.get(ack_seq)
		print(f"ACK entry={entry}")
		if entry is None:
			return

		if not entry.retransmitted and not entry.acked:
			rtt = self._network_time() - entry.time_sent
			if rtt >= 0:
				self.update_timeout(rtt)
			
		self.ack_block((self.last_ack_received + 1) % self.seq_space, ack_seq)


		entry.acked = True

	def process_sack_block(self, sack_block: SackBlock):
		self.ack_block(sack_block.sle, sack_block.sre)

	def update_window(self):
		while True:
			next_seq = (self.last_ack_received + 1) % self.seq_space
			entry = self.window.get(next_seq)
			if entry is None or not entry.acked:
				break

			self.fr_num_acks = 0
			
			self.last_ack_received = next_seq
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
		packet = Packet(
			data=encode_sw_payload(seq_num, payload),
			src=self.name,
			dst=self.receiver,
		)
		self.channels[0].send(packet)

		if seq_num not in self.window:
			self.window[seq_num] = _WindowEntry(
				acked=False,
				packet=packet,
				time_sent=self._network_time(),
				retransmitted=False,
			)

	def retransmit_timer(self):
		earliest_seq = (self.last_ack_received + 1) % self.seq_space
		if not self.is_in_window(earliest_seq):
			return

		entry = self.window.get(earliest_seq)
		if entry is None or entry.acked:
			return

		self.channels[0].send(entry.packet)
		entry.retransmitted = True
		print(f"RETRANS seq {earliest_seq} at time {self._network_time()} with RTO {self.retransmit_timeout}")
		self.retransmit_timeout = min(self.max_rto, max(self.min_rto, 2 * self.retransmit_timeout))
		self.set_timer(self.retransmit_timeout, self.retransmit_timer)

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
			current.retransmitted = True

			i = (i + 1) % self.seq_space
			if not self.is_in_window(i):
				break

			next_entry = self.window.get(i)
			in_unacked_block = next_entry is not None and not next_entry.acked

	def update_timeout(self, rtt: int):
   
		rtt_f = float(rtt)
		old = self.retransmit_timeout
		self.smoothed_variance = 0.9 * self.smoothed_variance + 0.1 * abs(self.smoothed_round_trip_time - rtt_f)
		self.smoothed_round_trip_time = 0.9 * self.smoothed_round_trip_time + 0.1 * rtt_f
		target_rto = int(round(self.smoothed_round_trip_time + 4.0 * self.smoothed_variance))
		print(f"target RTO={target_rto}")
		self.retransmit_timeout = self._clamp_rto(target_rto)
		print(f"Updating timeout with RTT={rtt} ms to RTO={self.retransmit_timeout} ms (previous RTO={old} ms)")

	def _clamp_rto(self, value: int) -> int:
		return max(self.min_rto, min(self.max_rto, int(value)))

	def _network_time(self) -> int:
		return int(self.network.sim.time)

	def is_complete(self) -> bool:
		return self.data_index >= len(self.data) and len(self.window) == 0

	def snapshot(self) -> List:
		return [self.retransmit_timeout, int(self.smoothed_round_trip_time), int(self.smoothed_variance)]
