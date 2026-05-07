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


class TCPServer(Node):
	"""
	Congestion-controlled reliable server combining:
	  - Sliding window with SACK
	  - Adaptive timeout (SRTT/Svar-based RTO)
	  - Fast retransmit / fast recovery (3 duplicate ACKs)
	  - Congestion window (AIMD) with slow start
	"""

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
		min_rto: int = 100,
		max_rto: int = 60_000,
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

		# Sliding Window / SACK
		self.seq_space = seq_space
		self.window_size = window_size
		self.window: dict[int, _WindowEntry] = {}
		self.last_ack_received = 0
		self.last_frame_sent = 0
		self.receiver = receiver
		self.data = data.encode("utf-8") if isinstance(data, str) else bytes(data)
		self.data_index = 0
		self.frame_size = frame_size

		# Adaptive Timeout
		self.min_rto = min_rto
		self.max_rto = max_rto
		self.retransmit_timeout = self._clamp_rto(retransmit_timeout)
		self.smoothed_rtt = -1.0
		self.smoothed_variance = -1.0

		# Fast Retransmit / Fast Recovery
		self.last_seq_acked = -1
		self.repeat_ack_count = 0

		# Congestion Window / AIMD
		self.congestion_window = 1
		self.ai_count = 0

		# Slow Start
		self.in_slow_start = True
		# Initial threshold set to window_size — represents "effectively infinite"
		# before the first timeout establishes a meaningful threshold.
		self.congestion_threshold = window_size

	def init(self):
		return None

	def start(self):
		for _ in range(self.effective_window()):
			next_chunk = self.next_data()
			if len(next_chunk) == 0:
				break
			next_seq = (self.last_frame_sent + 1) % self.seq_space
			self.send_frame(next_seq, next_chunk)
			self.last_frame_sent = next_seq

		# Start a single retransmit timer for the first unacked packet
		first_seq = (self.last_ack_received + 1) % self.seq_space
		self.set_timer(self.retransmit_timeout, self.retransmit_timer, first_seq)

	# ------------------------------------------------------------------
	# Effective window
	# ------------------------------------------------------------------

	def effective_window(self) -> int:
		"""The actual sending window: min(congestion_window, window_size)."""
		return min(self.congestion_window, self.window_size)

	# ------------------------------------------------------------------
	# Receive / ACK processing
	# ------------------------------------------------------------------

	def receive(self, packet: Packet):
		if packet.src != self.receiver:
			return

		decoded = decode_sack_payload(packet.data)
		if decoded is None:
			return

		ack_seq, sack_blocks = decoded
		print(
			f"[TCPServer] ACK seq={ack_seq} sack={sack_blocks} "
			f"cwnd={self.congestion_window} ss={self.in_slow_start} "
			f"cThresh={self.congestion_threshold} "
			f"window={list([key, p.acked] for key, p in self.window.items())}) "
			f"LAR={self.last_ack_received}"
		)
		self.handle_ack_packet(ack_seq, sack_blocks)

	def handle_ack_packet(self, ack_seq: int, sack_blocks: list[SackBlock]):
		# process_ack handles all filtering internally; we do NOT pre-filter by
		# is_in_window here so that duplicate ACKs (which have already slid past
		# the window) are still counted for fast retransmit.
		self.process_ack(ack_seq)
		for sack_block in sack_blocks:
			self.process_sack_block(sack_block)
		self.update_window()

	def process_ack(self, ack_seq: int):
		# --- Fast retransmit / fast recovery tracking ---
		# Runs for every incoming ACK, even those outside the current window.
		if ack_seq != self.last_seq_acked:
			self.last_seq_acked = ack_seq
			self.repeat_ack_count = 0
		else:
			self.repeat_ack_count += 1
			if self.repeat_ack_count == 3:
				# Trigger fast retransmit for the earliest unacked packet
				retransmit_seq = (self.last_ack_received + 1) % self.seq_space
				fr_entry = self.window.get(retransmit_seq)
				if fr_entry is not None and not fr_entry.acked:
					self.channels[0].send(fr_entry.packet)
					fr_entry.retransmitted = True
					print(f"[TCPServer] FAST RETRANSMIT seq={retransmit_seq}")
				self.repeat_ack_count = 0
				self.md_window()
				if self.in_slow_start:
					self.in_slow_start = False

		# --- Ack the cumulative range and this packet ---
		print(f"[TCPServer] ACKed block from {(self.last_ack_received + 1) % self.seq_space} to {ack_seq}")
		self.ack_block((self.last_ack_received + 1) % self.seq_space, ack_seq)
		
		# --- Congestion window update ---
		if self.in_slow_start:
			self.congestion_window = min(self.congestion_window + 1, self.window_size)
			if self.congestion_window >= self.congestion_threshold:
				self.in_slow_start = False
		else:
			# AIMD additive increase
			self.ai_count += 1
			if self.ai_count >= self.congestion_window:
				self.congestion_window = min(self.congestion_window + 1, self.window_size)
				self.ai_count = 0

    # Only continue processing if the ack refers to a packet in our window
		entry = self.window.get(ack_seq)
		if entry is None or entry.acked:
			return


		entry.acked = True

		# --- Adaptive timeout update ---
		# Only update with clean (non-retransmitted) RTT samples
		if not entry.retransmitted:
			rtt = self._network_time() - entry.time_sent
			if rtt >= 0:
				self.update_timeout(rtt)

	def process_sack_block(self, sack_block: SackBlock):
		self.ack_block(sack_block.sle, sack_block.sre)

	# ------------------------------------------------------------------
	# Window management
	# ------------------------------------------------------------------

	def update_window(self):
		# Slide the window forward past all consecutive acked packets
		moved = False
		while True:
			next_seq = (self.last_ack_received + 1) % self.seq_space
			entry = self.window.get(next_seq)
			if entry is None or not entry.acked:
				break
			print(f"[TCPServer] Window slide: last_ack_received={self.last_ack_received} -> {next_seq}")
			self.last_ack_received = next_seq
			del self.window[next_seq]
			moved = True

		# Fill the window up to effective_window with new data
		while self.seq_dist(self.last_ack_received, self.last_frame_sent) < self.effective_window():
			next_chunk = self.next_data()
			if len(next_chunk) == 0:
				break
			send_seq = (self.last_frame_sent + 1) % self.seq_space
			self.send_frame(send_seq, next_chunk)
			self.last_frame_sent = send_seq

		# When the window slides, start a fresh timer for the new earliest unacked
		# if moved and self.window:
		# 	new_earliest = (self.last_ack_received + 1) % self.seq_space
		# 	self.set_timer(self.retransmit_timeout, self.retransmit_timer, new_earliest)
		print(f"[TCPServer] window slid to last_ack_received={self.last_ack_received}")

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

	# ------------------------------------------------------------------
	# Retransmit timer
	# ------------------------------------------------------------------

	def retransmit_timer(self, seq_num: int):
		"""
		Fires for the earliest unacked packet.  Stale timers (for already-acked
		or superseded sequence numbers) are discarded silently.
		"""
		# Guard against stale timers: only act if seq_num is still the earliest
		if self.data_index >= len(self.data) and len(self.window) == 0:
			# All data sent and acked: no need to keep timers running
			return

		earliest = (self.last_ack_received + 1) % self.seq_space
		entry = self.window.get(seq_num)

		if seq_num != earliest or entry is None or entry.acked or not self.is_in_window(seq_num):
			self.network.schedule_after(self.retransmit_timeout, self.retransmit_timer, earliest)
			return

		# Retransmit the earliest unacked packet
		self.channels[0].send(entry.packet)
		entry.retransmitted = True
		print(
			f"[TCPServer] TIMEOUT seq={seq_num} "
			f"rto={self.retransmit_timeout} cwnd={self.congestion_window}"
		)

		# Exponential backoff and reschedule
		self.retransmit_timeout = self._clamp_rto(2 * self.retransmit_timeout)
		self.set_timer(self.retransmit_timeout, self.retransmit_timer, seq_num)

		# Congestion response: halve threshold, reset cwnd, re-enter slow start
		self.congestion_threshold = max(1, self.congestion_window // 2)
		self.congestion_window = 1
		self.in_slow_start = True

	# ------------------------------------------------------------------
	# Helper methods
	# ------------------------------------------------------------------

	def is_in_window(self, seq_num: int) -> bool:
		return 0 < self.seq_dist(self.last_ack_received, seq_num) <= self.window_size

	def seq_dist(self, left: int, right: int) -> int:
		"""Clockwise distance from left to right in the sequence number space."""
		return (right - left) % self.seq_space

	def ack_block(self, sle: int, sre: int):
		"""Mark all in-window entries in [sle, sre) as acked."""
		if self.seq_dist(sle, sre) > self.seq_space // 2:
			return
		i = sle % self.seq_space
		while i != sre % self.seq_space:
			if self.is_in_window(i):
				e = self.window.get(i)
				if e is not None:
					e.acked = True
			i = (i + 1) % self.seq_space

	def update_timeout(self, rtt: int):
		"""Update SRTT/Svar and recalculate RTO from a clean RTT sample."""
		rtt_f = float(rtt)
		if self.smoothed_rtt < 0:
			# First measurement: seed with exact sample
			self.smoothed_rtt = rtt_f
			self.smoothed_variance = rtt_f / 2.0
		else:
			self.smoothed_variance = (
				0.9 * self.smoothed_variance + 0.1 * abs(self.smoothed_rtt - rtt_f)
			)
			self.smoothed_rtt = 0.9 * self.smoothed_rtt + 0.1 * rtt_f
		target_rto = int(round(self.smoothed_rtt + 4.0 * self.smoothed_variance))
		self.retransmit_timeout = self._clamp_rto(target_rto)

	def md_window(self):
		"""Multiplicative decrease: halve the congestion window."""
		self.congestion_window = max(1, self.congestion_window // 2)

	def _clamp_rto(self, value: int) -> int:
		return max(self.min_rto, min(self.max_rto, int(value)))

	def _network_time(self) -> int:
		return int(self.network.sim.time)

	def is_complete(self) -> bool:
		return self.data_index >= len(self.data) and len(self.window) == 0

	def snapshot(self) -> List:
		return [
			self.congestion_window,
			self.congestion_threshold,
			self.retransmit_timeout,
			int(self.smoothed_rtt) if self.smoothed_rtt >= 0 else -1,
			int(self.smoothed_variance) if self.smoothed_variance >= 0 else -1,
			int(self.in_slow_start),
		]
