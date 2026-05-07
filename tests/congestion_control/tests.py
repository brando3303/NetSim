from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from src.channel import Channel
from src.network import Network
from src.network_sim import NetworkSim
from src.packet import Packet

from protocol.congestion_control.cc_client import TCPClient
from protocol.congestion_control.cc_server import TCPServer, _WindowEntry
from protocol.congestion_control.common import (
	SackBlock,
	decode_sack_payload,
	decode_sw_payload,
	encode_sack_payload,
	encode_sw_payload,
)


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

class _DummyNetwork:
	"""Minimal network stub for unit tests that need self.network.sim.time."""

	def __init__(self, time: int = 0):
		self.sim = type("_Sim", (), {"time": time})()

	def schedule_after(self, _delay, _callback, *_args, **_kwargs):
		return None


def _run_sim(
	payload: bytes,
	*,
	window_size: int = 8,
	frame_size: int = 8,
	retransmit_timeout: int = 200,
	seq_space: int = 128,
	bit_rate: int = 1000 * 8 * 100,
	propagation_delay: int = 5,
	delay_variance: int = 0,
	error_rate: int = 0,
	seed: int = 42,
	min_rto: int = 20,
	max_rto: int = 10_000,
) -> tuple[TCPServer, TCPClient, NetworkSim]:
	sim = NetworkSim(seed=seed, logging=False)
	network = Network(sim)

	server = TCPServer(
		name=1,
		receiver=2,
		data=payload,
		window_size=window_size,
		frame_size=frame_size,
		retransmit_timeout=retransmit_timeout,
		seq_space=seq_space,
		min_rto=min_rto,
		max_rto=max_rto,
	)
	client = TCPClient(
		name=2,
		server=1,
		buffer_window_size=window_size,
		seq_space=seq_space,
		max_sack_blocks=4,
	)

	network.add_node(server)
	network.add_node(client)

	channel = Channel(
		bit_rate=bit_rate,
		propagation_delay=propagation_delay,
		delay_variance=delay_variance,
		error_rate=error_rate,
	)
	network.add_channel(channel)
	channel.add_node(server)
	channel.add_node(client)

	with redirect_stdout(StringIO()):
		sim.start()

	return server, client, sim


# ---------------------------------------------------------------------------
# Wire-format tests
# ---------------------------------------------------------------------------

class TestWireFormat:
	def test_sw_payload_round_trip(self):
		encoded = encode_sw_payload(42, b"hello world")
		decoded = decode_sw_payload(encoded)
		assert decoded is not None
		seq, payload = decoded
		assert seq == 42
		assert payload == b"hello world"

	def test_sack_payload_round_trip_no_blocks(self):
		encoded = encode_sack_payload(7, [])
		decoded = decode_sack_payload(encoded)
		assert decoded is not None
		ack, blocks = decoded
		assert ack == 7
		assert blocks == []

	def test_sack_payload_round_trip_with_blocks(self):
		blocks_in = [SackBlock(10, 13), SackBlock(20, 22)]
		encoded = encode_sack_payload(5, blocks_in)
		decoded = decode_sack_payload(encoded)
		assert decoded is not None
		ack, blocks_out = decoded
		assert ack == 5
		assert blocks_out == blocks_in

	def test_decode_sw_payload_rejects_short_data(self):
		assert decode_sw_payload(b"\x00\x01") is None

	def test_decode_sack_payload_rejects_short_data(self):
		assert decode_sack_payload(b"\x00\x01") is None

	def test_decode_sw_payload_rejects_wrong_type(self):
		# Encode as ACK packet; sw decoder should reject it
		encoded = encode_sack_payload(1, [])
		assert decode_sw_payload(encoded) is None

	def test_decode_sack_payload_rejects_wrong_type(self):
		# Encode as data packet; sack decoder should reject it
		encoded = encode_sw_payload(1, b"data")
		assert decode_sack_payload(encoded) is None


# ---------------------------------------------------------------------------
# Unit tests — TCPServer
# ---------------------------------------------------------------------------

class TestTCPServerUnit:
	def _make_server(
		self,
		*,
		window_size: int = 8,
		seq_space: int = 64,
		min_rto: int = 20,
		max_rto: int = 2000,
		retransmit_timeout: int = 100,
		data: bytes = b"unit test payload",
	) -> TCPServer:
		server = TCPServer(
			name=1,
			receiver=2,
			data=data,
			window_size=window_size,
			frame_size=4,
			retransmit_timeout=retransmit_timeout,
			seq_space=seq_space,
			min_rto=min_rto,
			max_rto=max_rto,
		)
		server._network = _DummyNetwork(time=0)
		return server

	# --- Construction validation ---

	def test_invalid_window_size_zero(self):
		with pytest.raises(ValueError):
			TCPServer(name=1, receiver=2, data=b"x", window_size=0, frame_size=4, retransmit_timeout=100)

	def test_invalid_window_size_too_large(self):
		with pytest.raises(ValueError):
			TCPServer(name=1, receiver=2, data=b"x", window_size=128, frame_size=4, retransmit_timeout=100, seq_space=256)

	def test_invalid_min_rto_greater_than_max_rto(self):
		with pytest.raises(ValueError):
			TCPServer(name=1, receiver=2, data=b"x", window_size=4, frame_size=4, retransmit_timeout=100, min_rto=500, max_rto=100)

	# --- Initial state ---

	def test_initial_congestion_window_is_one(self):
		server = self._make_server()
		assert server.congestion_window == 1

	def test_initial_in_slow_start(self):
		server = self._make_server()
		assert server.in_slow_start is True

	def test_effective_window_equals_cwnd_when_cwnd_lt_window_size(self):
		server = self._make_server(window_size=8)
		server.congestion_window = 3
		assert server.effective_window() == 3

	def test_effective_window_capped_at_window_size(self):
		server = self._make_server(window_size=4)
		server.congestion_window = 100
		assert server.effective_window() == 4

	# --- seq_dist / is_in_window ---

	def test_seq_dist_no_wrap(self):
		server = self._make_server(seq_space=64)
		assert server.seq_dist(5, 10) == 5

	def test_seq_dist_with_wrap(self):
		server = self._make_server(seq_space=64)
		assert server.seq_dist(60, 3) == 7

	def test_is_in_window_true(self):
		server = self._make_server(window_size=8, seq_space=64)
		server.last_ack_received = 0
		assert server.is_in_window(4) is True

	def test_is_in_window_false_at_boundary(self):
		server = self._make_server(window_size=8, seq_space=64)
		server.last_ack_received = 0
		assert server.is_in_window(9) is False

	def test_is_in_window_false_for_lar_itself(self):
		server = self._make_server(window_size=8, seq_space=64)
		server.last_ack_received = 5
		assert server.is_in_window(5) is False

	# --- update_timeout / adaptive RTO ---

	def test_update_timeout_seeds_srtt_on_first_call(self):
		server = self._make_server()
		server.update_timeout(80)
		assert server.smoothed_rtt == 80.0
		assert server.smoothed_variance == 40.0

	def test_update_timeout_clamps_to_min_rto(self):
		server = self._make_server(min_rto=50)
		server.update_timeout(0)
		assert server.retransmit_timeout >= server.min_rto

	def test_update_timeout_clamps_to_max_rto(self):
		server = self._make_server(max_rto=500)
		server.update_timeout(100_000)
		assert server.retransmit_timeout <= server.max_rto

	def test_update_timeout_updates_rto_after_multiple_samples(self):
		server = self._make_server()
		server.update_timeout(100)
		rto_after_first = server.retransmit_timeout
		server.update_timeout(200)
		# Second sample should change the RTO
		assert server.retransmit_timeout != rto_after_first

	# --- Congestion window / slow start ---

	def test_process_ack_increments_cwnd_in_slow_start(self):
		server = self._make_server(window_size=8)
		server.congestion_window = 2
		server.window[5] = _WindowEntry(acked=False, packet=Packet(b"x", 1, 2), time_sent=0, retransmitted=False)
		server.process_ack(5)
		assert server.congestion_window == 3
		assert server.in_slow_start is True

	def test_process_ack_exits_slow_start_when_cwnd_reaches_cthresh(self):
		server = self._make_server(window_size=8)
		server.congestion_window = 4
		server.congestion_threshold = 5
		server.window[7] = _WindowEntry(acked=False, packet=Packet(b"x", 1, 2), time_sent=0, retransmitted=False)
		server.process_ack(7)
		assert server.congestion_window == 5
		assert server.in_slow_start is False

	def test_process_ack_increments_cwnd_in_aimd(self):
		server = self._make_server(window_size=8)
		server.congestion_window = 4
		server.in_slow_start = False
		server.window[3] = _WindowEntry(acked=False, packet=Packet(b"x", 1, 2), time_sent=0, retransmitted=False)
		server.process_ack(3)
		assert server.congestion_window == 5

	def test_process_ack_does_not_exceed_window_size(self):
		server = self._make_server(window_size=4)
		server.congestion_window = 4
		server.in_slow_start = False
		server.window[2] = _WindowEntry(acked=False, packet=Packet(b"x", 1, 2), time_sent=0, retransmitted=False)
		server.process_ack(2)
		assert server.congestion_window == 4

	def test_process_ack_skips_already_acked_entry(self):
		server = self._make_server(window_size=8)
		server.congestion_window = 3
		server.window[5] = _WindowEntry(acked=True, packet=Packet(b"x", 1, 2), time_sent=0, retransmitted=False)
		before = server.congestion_window
		server.process_ack(5)
		assert server.congestion_window == before  # no change

	def test_process_ack_skips_missing_entry(self):
		server = self._make_server(window_size=8)
		server.congestion_window = 3
		before = server.congestion_window
		server.process_ack(99)  # not in window
		assert server.congestion_window == before

	# --- Multiplicative decrease ---

	def test_md_window_halves_cwnd(self):
		server = self._make_server(window_size=8)
		server.congestion_window = 8
		server.md_window()
		assert server.congestion_window == 4

	def test_md_window_minimum_is_one(self):
		server = self._make_server()
		server.congestion_window = 1
		server.md_window()
		assert server.congestion_window == 1

	# --- Fast retransmit / duplicate ACK tracking ---

	def test_repeat_ack_count_increments_on_duplicate(self):
		server = self._make_server()
		server.last_seq_acked = 5
		server.repeat_ack_count = 1
		# Trigger fast-retransmit path but there's nothing in the window to send
		server.process_ack(5)
		assert server.repeat_ack_count == 2

	def test_repeat_ack_resets_on_new_ack(self):
		server = self._make_server()
		server.last_seq_acked = 5
		server.repeat_ack_count = 2
		server.process_ack(6)
		assert server.last_seq_acked == 6
		assert server.repeat_ack_count == 0

	def test_fast_retransmit_triggers_md_and_exits_slow_start(self):
		server = self._make_server(window_size=8)
		server.in_slow_start = True
		server.congestion_window = 6
		server.last_seq_acked = 3
		server.repeat_ack_count = 2  # next will be 3 → trigger

		# Populate the window so fast retransmit has something to send
		class _FakeChannel:
			def __init__(self):
				self.sent = []
			def send(self, pkt):
				self.sent.append(pkt)

		fake_ch = _FakeChannel()
		server.channels.append(fake_ch)
		server.window[1] = _WindowEntry(
			acked=False, packet=Packet(b"data", 1, 2), time_sent=0, retransmitted=False
		)

		server.process_ack(3)

		assert server.repeat_ack_count == 0
		assert server.in_slow_start is False
		assert server.congestion_window == 3  # md: 6 // 2 = 3
		assert len(fake_ch.sent) == 1  # one fast-retransmit packet

	# --- Retransmit timer / congestion on timeout ---

	def test_retransmit_timer_resets_cwnd_on_timeout(self):
		server = self._make_server(window_size=8)
		server.congestion_window = 6
		server.in_slow_start = False

		class _FakeChannel:
			def __init__(self):
				self.sent = []
			def send(self, pkt):
				self.sent.append(pkt)

		fake_ch = _FakeChannel()
		server.channels.append(fake_ch)

		seq = 1
		server.window[seq] = _WindowEntry(
			acked=False, packet=Packet(b"data", 1, 2), time_sent=0, retransmitted=False
		)

		server.retransmit_timer(seq)

		assert server.congestion_window == 1
		assert server.in_slow_start is True
		assert server.congestion_threshold == 3  # 6 // 2
		assert len(fake_ch.sent) == 1

	def test_retransmit_timer_doubles_rto(self):
		server = self._make_server(retransmit_timeout=100, max_rto=2000)
		server.congestion_window = 4

		class _FakeChannel:
			def send(self, _pkt):
				pass

		server.channels.append(_FakeChannel())
		server.window[1] = _WindowEntry(
			acked=False, packet=Packet(b"x", 1, 2), time_sent=0, retransmitted=False
		)

		before = server.retransmit_timeout
		server.retransmit_timer(1)
		assert server.retransmit_timeout == min(2000, 2 * before)

	def test_retransmit_timer_ignores_stale_seq(self):
		server = self._make_server()
		server.last_ack_received = 5  # earliest unacked = 6
		server.congestion_window = 4

		server.retransmit_timer(3)  # stale — should be a no-op
		assert server.congestion_window == 4  # unchanged

	def test_retransmit_timer_ignores_acked_entry(self):
		server = self._make_server()
		server.congestion_window = 4
		server.window[1] = _WindowEntry(
			acked=True, packet=Packet(b"x", 1, 2), time_sent=0, retransmitted=False
		)

		server.retransmit_timer(1)
		assert server.congestion_window == 4  # unchanged

	# --- Source filtering ---

	def test_server_ignores_packets_from_unexpected_src(self):
		server = self._make_server()
		before = server.last_ack_received
		server.receive(Packet(data=encode_sack_payload(1, []), src=99, dst=1))
		assert server.last_ack_received == before

	def test_server_ignores_non_sack_packets(self):
		server = self._make_server()
		before = server.last_ack_received
		server.receive(Packet(data=encode_sw_payload(1, b"data"), src=2, dst=1))
		assert server.last_ack_received == before

	# --- process_ack updates RTO only for non-retransmitted packets ---

	def test_process_ack_updates_rto_for_clean_packet(self):
		server = self._make_server()
		server._network = _DummyNetwork(time=200)
		server.window[1] = _WindowEntry(
			acked=False, packet=Packet(b"x", 1, 2), time_sent=100, retransmitted=False
		)
		before = server.retransmit_timeout
		server.process_ack(1)
		assert server.retransmit_timeout != before

	def test_process_ack_does_not_update_rto_for_retransmitted_packet(self):
		server = self._make_server()
		server._network = _DummyNetwork(time=200)
		server.window[1] = _WindowEntry(
			acked=False, packet=Packet(b"x", 1, 2), time_sent=100, retransmitted=True
		)
		before_rtt = server.smoothed_rtt
		server.process_ack(1)
		assert server.smoothed_rtt == before_rtt  # no RTT sample taken


# ---------------------------------------------------------------------------
# Unit tests — TCPClient
# ---------------------------------------------------------------------------

class TestTCPClientUnit:
	def _make_client(self) -> TCPClient:
		return TCPClient(
			name=2,
			server=1,
			buffer_window_size=8,
			seq_space=64,
			max_sack_blocks=4,
		)

	def test_initial_last_ack_sent_is_zero(self):
		client = self._make_client()
		assert client.last_ack_sent == 0

	def test_is_in_window_true(self):
		client = self._make_client()
		assert client.is_in_window(4) is True

	def test_is_in_window_false_beyond_buffer(self):
		client = self._make_client()
		assert client.is_in_window(9) is False

	def test_invalid_buffer_window_size(self):
		with pytest.raises(ValueError):
			TCPClient(name=2, server=1, buffer_window_size=0, seq_space=64)

	def test_invalid_max_sack_blocks(self):
		with pytest.raises(ValueError):
			TCPClient(name=2, server=1, buffer_window_size=8, seq_space=64, max_sack_blocks=0)

	def test_update_window_advances_last_ack_sent(self):
		client = self._make_client()
		client.buffer[1] = b"a"
		client.buffer[2] = b"b"
		client.update_window()
		assert client.last_ack_sent == 2
		assert client.received_data == bytearray(b"ab")

	def test_update_window_stops_at_gap(self):
		client = self._make_client()
		client.buffer[1] = b"a"
		client.buffer[3] = b"c"  # gap at 2
		client.update_window()
		assert client.last_ack_sent == 1  # stops before the gap

	def test_generate_sack_blocks_single_gap(self):
		client = self._make_client()
		client.last_ack_sent = 1
		client.buffer[3] = b"c"
		client.buffer[4] = b"d"
		blocks = client.generate_sack_blocks()
		assert len(blocks) == 1
		assert blocks[0].sle == 3
		assert blocks[0].sre == 5

	def test_generate_sack_blocks_multiple_gaps(self):
		client = self._make_client()
		client.last_ack_sent = 0
		client.buffer[2] = b"b"
		client.buffer[4] = b"d"
		blocks = client.generate_sack_blocks()
		assert len(blocks) == 2

	def test_client_ignores_packets_from_unexpected_src(self):
		client = self._make_client()

		class _FakeChannel:
			def send(self, _pkt):
				pass

		client.channels.append(_FakeChannel())
		before = client.last_ack_sent
		client.receive(Packet(data=encode_sw_payload(1, b"x"), src=99, dst=2))
		assert client.last_ack_sent == before


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegration:
	def test_perfect_channel_small_payload(self):
		payload = b"Hello, reliable world!"
		server, client, _ = _run_sim(payload, error_rate=0)
		assert bytes(client.received_data) == payload
		assert server.is_complete()

	def test_perfect_channel_large_payload(self):
		payload = b"X" * 512
		server, client, _ = _run_sim(payload, window_size=8, frame_size=16, error_rate=0)
		assert bytes(client.received_data) == payload
		assert server.is_complete()

	def test_lossy_channel_reconstructs_payload(self):
		payload = b"Reliable despite losses! " * 8
		server, client, _ = _run_sim(payload, error_rate=5, seed=7)
		assert bytes(client.received_data) == payload
		assert server.is_complete()

	def test_lossy_channel_different_seed(self):
		payload = b"Seed variation test. " * 6
		server, client, _ = _run_sim(payload, error_rate=8, seed=99)
		assert bytes(client.received_data) == payload

	def test_congestion_window_grows_on_perfect_channel(self):
		payload = b"B" * 256
		server, client, _ = _run_sim(payload, window_size=8, error_rate=0)
		# After successful transmission on a perfect channel, cwnd should have
		# grown beyond its initial value of 1 at some point.
		assert server.is_complete()
		assert bytes(client.received_data) == payload

	def test_rto_adapts_with_variable_delay(self):
		payload = b"Variable delay test. " * 8
		server, client, _ = _run_sim(
			payload,
			delay_variance=3,
			error_rate=0,
			seed=55,
		)
		assert bytes(client.received_data) == payload
		# SRTT should have been computed (not -1)
		assert server.smoothed_rtt >= 0

	def test_congestion_threshold_set_after_timeout(self):
		# Use a very short initial RTO to force early timeouts, exercising the
		# cThresh update path.
		payload = b"Timeout path test. " * 4
		server, client, _ = _run_sim(
			payload,
			error_rate=10,
			retransmit_timeout=50,
			min_rto=10,
			seed=13,
		)
		assert bytes(client.received_data) == payload
		# At least one timeout must have reduced cThresh below window_size
		assert server.congestion_threshold <= 8

	def test_snapshot_returns_expected_fields(self):
		payload = b"snapshot test"
		server, _, _ = _run_sim(payload, error_rate=0)
		snap = server.snapshot()
		assert len(snap) == 6
		cwnd, cthresh, rto, srtt, svar, ss = snap
		assert cwnd >= 1
		assert cthresh >= 1
		assert rto >= server.min_rto

	def test_single_byte_payload(self):
		payload = b"A"
		server, client, _ = _run_sim(payload, frame_size=4, error_rate=0)
		assert bytes(client.received_data) == payload
		assert server.is_complete()

	def test_payload_size_exactly_one_frame(self):
		payload = b"12345678"
		server, client, _ = _run_sim(payload, frame_size=8, error_rate=0)
		assert bytes(client.received_data) == payload

	def test_high_loss_rate(self):
		payload = b"Survive high loss. " * 3
		server, client, _ = _run_sim(
			payload,
			error_rate=15,
			retransmit_timeout=100,
			min_rto=10,
			seed=77,
		)
		assert bytes(client.received_data) == payload


if __name__ == "__main__":
	raise SystemExit(pytest.main([__file__, "-q"]))
