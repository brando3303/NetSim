"""Sliding-window-with-SACK sender (server) for NetSim.

The :class:`SWSACKServer` implements a Go-Back-N–style sender augmented with
Selective Acknowledgments (SACK).  Key design points:

* A fixed-size sequence space (default 256) is split into a sliding window of
  at most ``window_size`` frames in flight simultaneously.
* The window size must be strictly less than half the sequence space to avoid
  ambiguity between new and retransmitted frames after a wraparound.
* Retransmission is timer-based: each sent frame has its own independent
  retransmit timer; the timer is cancelled implicitly when the frame is acked.
* On receiving an ACK the server marks the cumulative range and any SACK blocks
  as acknowledged, slides the window forward, and immediately refills it with
  new data frames.  If SACK blocks are present it also retransmits the first
  contiguous unacked run to recover faster.
* ``is_complete()`` returns ``True`` once all data has been sent *and* all
  outstanding frames have been acknowledged.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.node import Node
from src.packet import Packet, packet_length

from .common import SackBlock, decode_sack_payload, encode_sw_payload


@dataclass(slots=True)
class _WindowEntry:
    """Tracks a single in-flight frame."""
    acked:  bool
    packet: Packet

class SWSACKServer(Node):
	"""Sliding-window sender with SACK-driven selective retransmission.

Sends a byte stream to a single receiver, tracking in-flight frames in a
dictionary keyed by sequence number.  Sequence numbers are modular (wrap
at ``seq_space``).

Attributes:
		seq_space:          Size of the sequence number space (must be > 2 and
												``window_size < seq_space // 2``).
		window_size:        Maximum number of unacknowledged frames in flight.
		window:             Dict mapping seq_num -> :class:`_WindowEntry`.
		last_ack_received:  Highest cumulative ACK received so far.
		last_frame_sent:    Sequence number of the most recently transmitted frame.
		receiver:           Name (node ID) of the destination node.
		data:               Full byte string to transmit.
		data_index:         Byte offset into ``data``; marks how far we have
												sliced new frames from the buffer.
		frame_size:         Maximum payload bytes per frame.
		retransmit_timeout: Fixed retransmit timeout in ms for this variant.
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
	):
		"""Construct the SACK sender.

		Args:
			name:               Node ID used as ``src`` in outgoing packets.
			receiver:           Node ID of the destination (receiver) node.
			data:               Byte string (or UTF-8 str) to deliver reliably.
			window_size:        Max unacknowledged frames in flight at once.
			frame_size:         Max payload bytes per frame.
			retransmit_timeout: Fixed retransmit timeout in ms.
			seq_space:          Sequence number modulus.  Must be > 2 and
			                    ``window_size < seq_space // 2``.
		"""
		super().__init__(name)

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
		"""Fill the send window with the first ``window_size`` data frames."""
		for _ in range(self.window_size):
			next_chunk = self.next_data()
			if len(next_chunk) == 0:
				break
			next_seq = (self.last_frame_sent + 1) % self.seq_space
			self.send_frame(next_seq, next_chunk)
			self.last_frame_sent = next_seq

		first_seq = (self.last_ack_received + 1) % self.seq_space
		self.set_timer(self.retransmit_timeout, self.retransmit_timer, first_seq)

	def receive(self, packet: Packet):
		"""Handle an incoming packet (expected to be an ACK from the receiver)."""
		if packet.src != self.receiver:
			return

		decoded = decode_sack_payload(packet.data)
		if decoded is None:
			return

		ack_seq, sack_blocks = decoded
		self.handle_ack_packet(ack_seq, sack_blocks)

	def handle_ack_packet(self, ack_seq: int, sack_blocks: list[SackBlock]):
		"""Process a decoded ACK: mark frames acked, slide window, refill, retransmit."""
		print("recieved ack", ack_seq, sack_blocks, " LAR=", self.last_ack_received)
		if not self.is_in_window(ack_seq):
			return

		self.process_ack(ack_seq)
		for sack_block in sack_blocks:
			self.process_sack_block(sack_block)

		self.update_window()

		if len(sack_blocks) > 0:
			self.retransmit_next_block()

	def process_ack(self, ack_seq: int):
		"""Mark all frames from ``last_ack_received+1`` up to *ack_seq* as acked."""
		# ack_block handles the cumulative ACK range (last_ack+1 .. ack_seq)
		self.ack_block((self.last_ack_received + 1) % self.seq_space, ack_seq)
		entry = self.window.get(ack_seq)
		if entry is None:
			return
		print(f"ACKed seq_num={ack_seq}")
		entry.acked = True

	def process_sack_block(self, sack_block: SackBlock):
		"""Mark the half-open range ``[sle, sre)`` of sequence numbers as acked."""
		self.ack_block(sack_block.sle, sack_block.sre)

	def update_window(self):
		"""Slide the window forward over contiguous acked frames and send new ones."""
		while True:
			next_seq = (self.last_ack_received + 1) % self.seq_space
			entry = self.window.get(next_seq)
			if entry is None or not entry.acked:
				break

			self.last_ack_received = next_seq
			del self.window[next_seq]

			next_chunk = self.next_data()
			if len(next_chunk) == 0:
				continue

			send_seq = (self.last_frame_sent + 1) % self.seq_space
			print(f"slid window to {self.last_ack_received}, delivered seq_num={next_seq}")

			self.send_frame(send_seq, next_chunk)
			self.last_frame_sent = send_seq

	def next_data(self) -> bytes:
		"""Return the next ``frame_size`` bytes from the data buffer (or fewer if near end)."""
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
			self.window[seq_num] = _WindowEntry(acked=False, packet=packet)

	def retransmit_timer(self, seq_num: int):
		"""Retransmit callback: resend frame *seq_num* if still unacked and in window."""
		print(f"retransmit timer fired for seq_num={seq_num}")
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

		self.set_timer(self.retransmit_timeout, self.retransmit_timer, seq_num)


	def is_in_window(self, seq_num: int) -> bool:
		return 0 < self.seq_dist(self.last_ack_received, seq_num) <= self.window_size

	def seq_dist(self, left: int, right: int) -> int:
		return (right - left) % self.seq_space

	def ack_block(self, sle: int, sre: int):
		"""Mark every in-window sequence number in half-open range ``[sle, sre)`` as acked.

		The guard ``seq_dist(sle, sre) > seq_space // 2`` discards ranges that
		wrap backwards more than half the sequence space, which would indicate a
		stale or malformed block.
		"""
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
		"""Retransmit the leading contiguous run of unacked frames in the window.

		Called after processing SACK blocks so that gaps at the front of the
		window are retransmitted promptly without waiting for a timer.
		"""
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
			#self.set_timer(self.retransmit_timeout, self.retransmit_timer, i)

			i = (i + 1) % self.seq_space
			if not self.is_in_window(i):
				break
			next_entry = self.window.get(i)
			in_unacked_block = next_entry is not None and not next_entry.acked

	def is_complete(self) -> bool:
		"""Return ``True`` once all data has been sent and all frames acknowledged."""
		return self.data_index >= len(self.data) and len(self.window) == 0
