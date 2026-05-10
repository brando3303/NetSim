"""Adaptive-timeout SACK sender (server) for NetSim.

Extends the sliding-window SACK sender with two improvements:

1. **Adaptive RTO** — The retransmit timeout is calculated using the
   Jacobson/Karels algorithm (RFC 6298):
   ``SRTT = 0.9*SRTT + 0.1*RTT``  (exponential weighted moving average)
   ``SVAR = 0.9*SVAR + 0.1*|SRTT - RTT|``  (smoothed mean deviation)
   ``RTO  = SRTT + 4*SVAR``  clamped to ``[min_rto, max_rto]``
   Only un-retransmitted frames are used to sample RTT so that the Karn
   ambiguity problem is avoided.

2. **Fast retransmit** — If the same cumulative ACK sequence number is
   received three times in a row the sender immediately retransmits the
   oldest unacknowledged frame without waiting for the RTO timer.

The global RTO timer fires at the current timeout interval and only
retransmits the *earliest* unacknowledged frame (head-of-line).  After
each timer-triggered retransmission the RTO is doubled (exponential
back-off) until a clean ACK is received, at which point ``update_timeout``
resets it back to the SRTT estimate.

Here we have included a means to guess the retransmittion timeout so that a user wouldn't need to manually set
it each time they wanted to use the protocol. We are still needing to set the window size and hope for the best, 
but we'll see better ways to do this.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.node import Node
from src.packet import Packet

from .common import SackBlock, decode_sack_payload, encode_sw_payload


@dataclass(slots=True)
class _WindowEntry:
    """Tracks a single in-flight frame with RTT-sampling metadata."""
    acked:         bool
    packet:        Packet
    time_sent:     int   # simulator time (ms) when the frame was first sent
    retransmitted: bool  # True if this frame has been retransmitted (skip RTT sample)


class ATServer(Node):
	"""Sliding-window sender with adaptive RTO and fast retransmit.

	Attributes:
		seq_space:                 Size of the sequence number space.
		window_size:               Maximum unacknowledged frames in flight.
		window:                    Dict mapping seq_num -> :class:`_WindowEntry`.
		last_ack_received:         Highest cumulative ACK received so far.
		last_frame_sent:           Sequence number of the last transmitted frame.
		receiver:                  Destination node ID.
		data:                      Full byte string to deliver.
		data_index:                Byte offset into ``data`` (slicing cursor).
		frame_size:                Max payload bytes per DATA frame.
		min_rto:                   Lower bound on the computed RTO (ms).
		max_rto:                   Upper bound on the computed RTO (ms).
		retransmit_timeout:        Current RTO estimate (ms).
		smoothed_round_trip_time:  SRTT estimate; -1 before first sample.
		smoothed_variance:         SVAR estimate; -1 before first sample.
		rto_timer_running:         Whether the global retransmit timer is active.
		fr_num_acks:               Duplicate-ACK counter for fast retransmit.
		fr_last_seen_seq:          Sequence number of the most recent ACK seen.
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
		self.smoothed_round_trip_time = -1
		self.smoothed_variance = -1

		self.rto_timer_running = False
		self.fr_num_acks = 0
		self.fr_last_seen_seq = None

	def init(self):
		return None

	def start(self):
		"""Fill the send window and start the global RTO timer."""
		for _ in range(self.window_size):
			next_chunk = self.next_data()
			if len(next_chunk) == 0:
				break

			next_seq = (self.last_frame_sent + 1) % self.seq_space
			self.send_frame(next_seq, next_chunk)
			self.last_frame_sent = next_seq

		if not self.rto_timer_running:
			self.set_timer(self.retransmit_timeout, self.retransmit_timer)
			self.rto_timer_running = True

		

	def receive(self, packet: Packet):
		if packet.src != self.receiver:
			return

		decoded = decode_sack_payload(packet.data)
		if decoded is None:
			return

		ack_seq, sack_blocks = decoded
		self.handle_ack_packet(ack_seq, sack_blocks)

	def handle_ack_packet(self, ack_seq: int, sack_blocks: list[SackBlock]):
		"""Process a decoded ACK with fast-retransmit detection.

		If the same *ack_seq* is received three times without advancing the
		cumulative ACK (duplicate ACKs), the oldest unacked frame is immediately
		retransmitted (fast retransmit) without waiting for the RTO timer.
		"""
		# increase fast retransmit counter even if ACK is correct
		if not self.is_in_window(ack_seq):
			return


		self.process_ack(ack_seq)
		for sack_block in sack_blocks:
			self.process_sack_block(sack_block)

		if self.fr_last_seen_seq == ack_seq:
			self.fr_num_acks += 1
			if self.fr_num_acks == 3:
				entry = self.window.get(ack_seq)
				if entry is not None and not entry.acked:
					self.channels[0].send(entry.packet)
					entry.retransmitted = True
		else:
			self.fr_num_acks = 1
			self.fr_last_seen_seq = ack_seq

		self.update_window()

		if len(sack_blocks) > 0:
			self.retransmit_next_block()

	def process_ack(self, ack_seq: int):
		"""Sample RTT from an un-retransmitted frame and mark the cumulative range acked."""
		entry = self.window.get(ack_seq)
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
		"""Global RTO timer callback: retransmit head-of-line and double the RTO.

		Only the oldest unacknowledged frame (lowest sequence number in window)
		is retransmitted on each timer firing.  The RTO is doubled (exponential
		back-off) up to ``max_rto`` so that the sender backs off under congestion.
		"""
		earliest_seq = (self.last_ack_received + 1) % self.seq_space
		if not self.is_in_window(earliest_seq):
			return

		entry = self.window.get(earliest_seq)
		if entry is None or entry.acked:
			return

		self.channels[0].send(entry.packet)
		entry.retransmitted = True
		# Exponential back-off: double RTO until max is reached.
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
		"""Update the adaptive RTO using the Jacobson/Karels EWMA algorithm.

		On the first sample ``SRTT`` and ``SVAR`` are seeded directly.  On
		subsequent samples both are updated with EWMA weights 0.9/0.1:
		
		    SRTT = 0.9 * SRTT + 0.1 * rtt
		    SVAR = 0.9 * SVAR + 0.1 * |SRTT_prev - rtt|
		    RTO  = round(SRTT + 4 * SVAR)  clamped to [min_rto, max_rto]
		"""
		if self.smoothed_round_trip_time < 0:
			self.smoothed_round_trip_time = float(rtt)
			self.smoothed_variance = float(rtt) / 2
			return
   
		rtt_f = float(rtt)
		self.smoothed_variance = 0.9 * self.smoothed_variance + 0.1 * abs(self.smoothed_round_trip_time - rtt_f)
		self.smoothed_round_trip_time = 0.9 * self.smoothed_round_trip_time + 0.1 * rtt_f
		target_rto = int(round(self.smoothed_round_trip_time + 4.0 * self.smoothed_variance))
		self.retransmit_timeout = self._clamp_rto(target_rto)

	def _clamp_rto(self, value: int) -> int:
		"""Clamp *value* to ``[min_rto, max_rto]``."""
		return max(self.min_rto, min(self.max_rto, int(value)))

	def _network_time(self) -> int:
		"""Return the current simulator time in milliseconds."""
		return int(self.network.sim.time)

	def is_complete(self) -> bool:
		"""Return ``True`` once all data has been sent and all frames acknowledged."""
		return self.data_index >= len(self.data) and len(self.window) == 0

	def snapshot(self) -> List:
		"""Return ``[rto, srtt, svar]`` for periodic analytics plotting."""
		return [self.retransmit_timeout, int(self.smoothed_round_trip_time), int(self.smoothed_variance)]
