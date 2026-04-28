"""Tests for the SlidingWindow SACK protocol.

Covers three layers:
  1. Wire format – encode/decode round-trips for SWPacket and SACKPacket payloads.
  2. Unit – isolated method behaviour on server and client (no simulator needed).
  3. Integration – full simulator runs with various channel conditions.
"""
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

from protocol.sliding_window_sack.common import (
    SackBlock,
    decode_sack_payload,
    decode_sw_payload,
    encode_sack_payload,
    encode_sw_payload,
)
from protocol.sliding_window_sack.swsack_client import SWSACKClient
from protocol.sliding_window_sack.swsack_server import SWSACKServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_sim(
    payload: bytes,
    *,
    window_size: int = 4,
    frame_size: int = 8,
    retransmit_timeout: int = 20,
    seq_space: int = 64,
    bit_rate: int = 1000 * 8 * 100,
    propagation_delay: int = 2,
    delay_variance: int = 0,
    error_rate: int = 0,
    seed: int = 42,
) -> tuple[SWSACKServer, SWSACKClient, NetworkSim]:
    sim = NetworkSim(seed=seed, logging=False)
    network = Network(sim)

    server = SWSACKServer(
        name=1,
        receiver=2,
        data=payload,
        window_size=window_size,
        frame_size=frame_size,
        retransmit_timeout=retransmit_timeout,
        seq_space=seq_space,
    )
    client = SWSACKClient(
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
# 1. Wire-format tests
# ---------------------------------------------------------------------------

class TestWireFormat:
    def test_sw_payload_round_trip_preserves_seq_and_data(self):
        encoded = encode_sw_payload(7, b"hello")
        result = decode_sw_payload(encoded)
        assert result is not None
        seq, data = result
        assert seq == 7
        assert data == b"hello"

    def test_sw_payload_round_trip_with_empty_payload(self):
        encoded = encode_sw_payload(0, b"")
        result = decode_sw_payload(encoded)
        assert result is not None
        seq, data = result
        assert seq == 0
        assert data == b""

    def test_sw_payload_round_trip_with_binary_data(self):
        raw = bytes(range(256))
        encoded = encode_sw_payload(255, raw)
        result = decode_sw_payload(encoded)
        assert result is not None
        seq, data = result
        assert seq == 255
        assert data == raw

    def test_decode_sw_payload_returns_none_for_short_input(self):
        assert decode_sw_payload(b"\x00\x01") is None

    def test_decode_sw_payload_returns_none_for_wrong_magic(self):
        encoded = bytearray(encode_sw_payload(1, b"x"))
        encoded[0] ^= 0xFF  # corrupt magic
        assert decode_sw_payload(bytes(encoded)) is None

    def test_decode_sw_payload_accepts_str_input(self):
        encoded = encode_sw_payload(3, b"abc")
        # str path: should return None (not a DATA type string)
        result = decode_sw_payload(encoded.decode("latin-1"))
        assert result is not None
        assert result[0] == 3

    def test_sack_payload_round_trip_no_blocks(self):
        encoded = encode_sack_payload(5, [])
        result = decode_sack_payload(encoded)
        assert result is not None
        ack_seq, blocks = result
        assert ack_seq == 5
        assert blocks == []

    def test_sack_payload_round_trip_with_one_block(self):
        block = SackBlock(sle=3, sre=6)
        encoded = encode_sack_payload(2, [block])
        result = decode_sack_payload(encoded)
        assert result is not None
        ack_seq, blocks = result
        assert ack_seq == 2
        assert len(blocks) == 1
        assert blocks[0].sle == 3
        assert blocks[0].sre == 6

    def test_sack_payload_round_trip_with_multiple_blocks(self):
        input_blocks = [SackBlock(1, 3), SackBlock(5, 7), SackBlock(9, 11)]
        encoded = encode_sack_payload(0, input_blocks)
        result = decode_sack_payload(encoded)
        assert result is not None
        ack_seq, blocks = result
        assert ack_seq == 0
        assert [(b.sle, b.sre) for b in blocks] == [(1, 3), (5, 7), (9, 11)]

    def test_decode_sack_payload_returns_none_for_wrong_magic(self):
        encoded = bytearray(encode_sack_payload(1, []))
        encoded[0] ^= 0xFF
        assert decode_sack_payload(bytes(encoded)) is None

    def test_decode_sack_payload_returns_none_for_truncated_blocks(self):
        encoded = encode_sack_payload(1, [SackBlock(0, 1)])
        # truncate the block data
        assert decode_sack_payload(encoded[:-1]) is None

    def test_sack_payload_caps_at_255_blocks(self):
        blocks = [SackBlock(i, i + 1) for i in range(300)]
        encoded = encode_sack_payload(0, blocks)
        result = decode_sack_payload(encoded)
        assert result is not None
        _, decoded_blocks = result
        assert len(decoded_blocks) == 255


# ---------------------------------------------------------------------------
# 2. Unit tests – server helper methods
# ---------------------------------------------------------------------------

class TestServerUnit:
    def _make_server(self, *, window_size=4, seq_space=16) -> SWSACKServer:
        server = SWSACKServer(
            name=1, receiver=2, data=b"x" * 32,
            window_size=window_size, frame_size=4,
            retransmit_timeout=10, seq_space=seq_space,
        )
        return server

    def test_seq_dist_forward_distance(self):
        s = self._make_server(seq_space=16)
        assert s.seq_dist(2, 5) == 3

    def test_seq_dist_wraparound(self):
        s = self._make_server(seq_space=16)
        assert s.seq_dist(14, 2) == 4

    def test_seq_dist_zero_distance(self):
        s = self._make_server(seq_space=16)
        assert s.seq_dist(3, 3) == 0

    def test_is_in_window_true_for_seq_within_window(self):
        s = self._make_server(window_size=4, seq_space=16)
        # LAR=0, window covers 1..4
        assert s.is_in_window(1) is True
        assert s.is_in_window(4) is True

    def test_is_in_window_false_for_seq_at_lar(self):
        s = self._make_server(window_size=4, seq_space=16)
        assert s.is_in_window(0) is False

    def test_is_in_window_false_beyond_window(self):
        s = self._make_server(window_size=4, seq_space=16)
        assert s.is_in_window(5) is False

    def test_is_in_window_true_across_wraparound(self):
        s = self._make_server(window_size=4, seq_space=16)
        s.last_ack_received = 14
        assert s.is_in_window(15) is True
        assert s.is_in_window(0) is True
        assert s.is_in_window(1) is True
        assert s.is_in_window(2) is True
        assert s.is_in_window(3) is False  # one past window

    def test_ack_block_marks_entries_in_range(self):
        from protocol.sliding_window_sack.swsack_server import _WindowEntry
        s = self._make_server(window_size=4, seq_space=16)
        for i in [1, 2, 3]:
            s.window[i] = _WindowEntry(acked=False, packet=Packet(b"", 1, 2))
        s.ack_block(1, 4)
        assert s.window[1].acked is True
        assert s.window[2].acked is True
        assert s.window[3].acked is True

    def test_ack_block_does_not_mark_entries_outside_window(self):
        from protocol.sliding_window_sack.swsack_server import _WindowEntry
        s = self._make_server(window_size=4, seq_space=16)
        s.window[5] = _WindowEntry(acked=False, packet=Packet(b"", 1, 2))
        s.ack_block(1, 6)  # 5 is outside the window [1..4]
        assert s.window[5].acked is False

    def test_ack_block_guards_against_large_range(self):
        """A range larger than seq_space // 2 should be a no-op."""
        from protocol.sliding_window_sack.swsack_server import _WindowEntry
        s = self._make_server(window_size=4, seq_space=16)
        s.window[1] = _WindowEntry(acked=False, packet=Packet(b"", 1, 2))
        # sle=1, sre=0 wraps around with dist=15 which is > 8; should not ack
        s.ack_block(1, 0)
        assert s.window[1].acked is False

    def test_constructor_rejects_window_size_too_large(self):
        with pytest.raises(ValueError, match="half"):
            SWSACKServer(name=1, receiver=2, data=b"x",
                         window_size=8, frame_size=4,
                         retransmit_timeout=10, seq_space=16)

    def test_constructor_rejects_zero_window_size(self):
        with pytest.raises(ValueError):
            SWSACKServer(name=1, receiver=2, data=b"x",
                         window_size=0, frame_size=4,
                         retransmit_timeout=10, seq_space=64)

    def test_constructor_rejects_zero_frame_size(self):
        with pytest.raises(ValueError):
            SWSACKServer(name=1, receiver=2, data=b"x",
                         window_size=4, frame_size=0,
                         retransmit_timeout=10, seq_space=64)

    def test_constructor_rejects_zero_retransmit_timeout(self):
        with pytest.raises(ValueError):
            SWSACKServer(name=1, receiver=2, data=b"x",
                         window_size=4, frame_size=4,
                         retransmit_timeout=0, seq_space=64)

    def test_is_complete_false_when_data_unsent(self):
        s = self._make_server()
        assert s.is_complete() is False

    def test_is_complete_true_when_all_data_sent_and_window_empty(self):
        s = self._make_server()
        s.data_index = len(s.data)
        # window is already empty
        assert s.is_complete() is True

    def test_next_data_advances_index_correctly(self):
        s = self._make_server()
        first = s.next_data()
        assert len(first) == s.frame_size
        assert s.data_index == s.frame_size

    def test_next_data_returns_empty_when_exhausted(self):
        s = self._make_server()
        s.data_index = len(s.data)
        assert s.next_data() == b""

    def test_next_data_returns_partial_chunk_at_end(self):
        s = SWSACKServer(
            name=1, receiver=2, data=b"abc",
            window_size=4, frame_size=8,
            retransmit_timeout=10, seq_space=64,
        )
        chunk = s.next_data()
        assert chunk == b"abc"


# ---------------------------------------------------------------------------
# 3. Unit tests – client helper methods
# ---------------------------------------------------------------------------

class TestClientUnit:
    def _make_client(self, *, buffer_window_size=4, seq_space=16) -> SWSACKClient:
        return SWSACKClient(
            name=2, server=1,
            buffer_window_size=buffer_window_size,
            seq_space=seq_space,
            max_sack_blocks=4,
        )

    def test_is_in_window_true_for_next_seq(self):
        c = self._make_client()
        assert c.is_in_window(1) is True

    def test_is_in_window_false_for_las_itself(self):
        c = self._make_client()
        assert c.is_in_window(0) is False

    def test_is_in_window_false_beyond_buffer_window(self):
        c = self._make_client(buffer_window_size=4, seq_space=16)
        assert c.is_in_window(5) is False

    def test_is_in_window_wraparound(self):
        c = self._make_client(buffer_window_size=4, seq_space=16)
        c.last_ack_sent = 14
        assert c.is_in_window(15) is True
        assert c.is_in_window(0) is True
        assert c.is_in_window(2) is True
        assert c.is_in_window(3) is False

    def test_generate_sack_blocks_empty_when_buffer_empty(self):
        c = self._make_client()
        assert c.generate_sack_blocks() == []

    def test_generate_sack_blocks_single_contiguous_block(self):
        c = self._make_client(buffer_window_size=8, seq_space=32)
        # seq 1 missing, seq 2 and 3 present
        c.buffer[2] = b"a"
        c.buffer[3] = b"b"
        blocks = c.generate_sack_blocks()
        assert len(blocks) == 1
        assert blocks[0].sle == 2
        assert blocks[0].sre == 4

    def test_generate_sack_blocks_two_gaps(self):
        c = self._make_client(buffer_window_size=8, seq_space=32)
        # 1 missing, 2 present, 3 missing, 4 present
        c.buffer[2] = b"a"
        c.buffer[4] = b"b"
        blocks = c.generate_sack_blocks()
        assert len(blocks) == 2
        assert (blocks[0].sle, blocks[0].sre) == (2, 3)
        assert (blocks[1].sle, blocks[1].sre) == (4, 5)

    def test_generate_sack_blocks_respects_max_sack_blocks(self):
        c = SWSACKClient(
            name=2, server=1, buffer_window_size=10,
            seq_space=32, max_sack_blocks=2,
        )
        # create 3 separate blocks of buffered data with gaps between each
        c.buffer[2] = b"a"
        c.buffer[4] = b"b"
        c.buffer[6] = b"c"
        blocks = c.generate_sack_blocks()
        assert len(blocks) <= 2

    def test_generate_sack_blocks_block_ending_at_window_edge(self):
        c = self._make_client(buffer_window_size=4, seq_space=16)
        # whole window is buffered but seq 1 is missing
        c.buffer[2] = b"a"
        c.buffer[3] = b"b"
        c.buffer[4] = b"c"
        blocks = c.generate_sack_blocks()
        # last buffered seq is at window edge, block should close at 5
        assert len(blocks) == 1
        assert blocks[0].sle == 2
        assert blocks[0].sre == 5

    def test_update_window_advances_las_on_contiguous_buffer(self):
        c = self._make_client(seq_space=16)
        c.buffer[1] = b"a"
        c.buffer[2] = b"b"
        c.buffer[3] = b"c"
        c.update_window()
        assert c.last_ack_sent == 3
        assert bytes(c.received_data) == b"abc"
        assert len(c.buffer) == 0

    def test_update_window_stops_at_gap(self):
        c = self._make_client(seq_space=16)
        c.buffer[1] = b"a"
        # seq 2 missing
        c.buffer[3] = b"c"
        c.update_window()
        assert c.last_ack_sent == 1
        assert bytes(c.received_data) == b"a"
        assert 3 in c.buffer

    def test_update_window_wraparound(self):
        # seq_space=10 -> max buffer_window_size=4 (< 10//2=5)
        c = self._make_client(buffer_window_size=4, seq_space=10)
        c.last_ack_sent = 8
        c.buffer[9] = b"x"
        c.buffer[0] = b"y"
        c.update_window()
        assert c.last_ack_sent == 0
        assert bytes(c.received_data) == b"xy"

    def test_constructor_rejects_buffer_window_size_too_large(self):
        with pytest.raises(ValueError, match="half"):
            SWSACKClient(name=2, server=1,
                         buffer_window_size=8, seq_space=16)

    def test_constructor_rejects_zero_buffer_window_size(self):
        with pytest.raises(ValueError):
            SWSACKClient(name=2, server=1,
                         buffer_window_size=0, seq_space=64)

    def test_constructor_rejects_zero_max_sack_blocks(self):
        with pytest.raises(ValueError):
            SWSACKClient(name=2, server=1,
                         buffer_window_size=4, seq_space=64,
                         max_sack_blocks=0)


# ---------------------------------------------------------------------------
# 4. Integration tests – full simulation runs
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_perfect_channel_delivers_exact_payload(self):
        payload = b"hello world"
        server, client, _ = _run_sim(payload, error_rate=0)
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_perfect_channel_data_fits_in_single_frame(self):
        payload = b"hi"
        server, client, _ = _run_sim(payload, frame_size=16, window_size=4)
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_empty_payload_completes_immediately(self):
        server, client, sim = _run_sim(b"", error_rate=0, seq_space=64)
        assert bytes(client.received_data) == b""
        assert server.is_complete()
        # No data frames should ever have been sent
        assert server.last_frame_sent == 0

    def test_payload_exactly_one_frame_size(self):
        payload = b"12345678"
        server, client, _ = _run_sim(payload, frame_size=8, window_size=4)
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_payload_smaller_than_window_capacity(self):
        # Only 2 frames worth of data with window_size=8
        payload = b"abcdefghijklmnop"
        server, client, _ = _run_sim(
            payload, window_size=8, frame_size=8, seq_space=64,
        )
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_larger_payload_with_many_frames(self):
        payload = bytes(range(256))
        server, client, _ = _run_sim(
            payload, window_size=8, frame_size=16, seq_space=128,
        )
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_delivery_with_high_delay_variance(self):
        payload = b"out of order test" * 4
        server, client, _ = _run_sim(
            payload,
            delay_variance=50,
            propagation_delay=5,
            retransmit_timeout=200,
            window_size=6,
            frame_size=8,
            seq_space=64,
        )
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_delivery_survives_moderate_error_rate(self):
        payload = b"lossy channel test " * 8
        server, client, _ = _run_sim(
            payload,
            error_rate=30,
            retransmit_timeout=20,
            window_size=6,
            frame_size=12,
            seq_space=128,
            seed=99,
        )
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_completion_time_decreases_with_larger_window(self):
        payload = b"x" * 128
        kwargs = dict(frame_size=8, seq_space=128, error_rate=0,
                      propagation_delay=4, seed=1)
        _, _, sim_small = _run_sim(payload, window_size=1, **kwargs)
        _, _, sim_large = _run_sim(payload, window_size=8, **kwargs)
        assert sim_large.time < sim_small.time

    def test_duplicate_frames_do_not_corrupt_payload(self):
        """A frame re-sent by the retransmit timer must not duplicate data."""
        payload = b"dedup test payload here!!"
        server, client, _ = _run_sim(
            payload,
            # very short retransmit timeout causes many retransmits
            retransmit_timeout=1,
            window_size=4,
            frame_size=8,
            seq_space=64,
            error_rate=0,
            propagation_delay=5,
            seed=7,
        )
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_payload_is_byte_for_byte_identical_after_transfer(self):
        payload = bytes(range(256)) * 2
        server, client, _ = _run_sim(
            payload,
            window_size=8,
            frame_size=16,
            seq_space=128,
            error_rate=0,
        )
        assert bytes(client.received_data) == payload

    def test_sequence_number_wraparound(self):
        """Use a very small seq_space to force wraparound during the transfer."""
        payload = b"wraparound" * 6
        server, client, _ = _run_sim(
            payload,
            seq_space=16,   # window=4, half-seq=8; 60 bytes / 4 bytes = 15 frames
            window_size=4,
            frame_size=4,
            retransmit_timeout=30,
            error_rate=0,
            propagation_delay=2,
        )
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_server_ignores_packets_from_unexpected_src(self):
        payload = b"filter test"
        server, client, _ = _run_sim(payload, error_rate=0)
        pre_lar = server.last_ack_received
        # inject a spoofed ACK from node 99
        raw_ack = encode_sack_payload(pre_lar + 1, [])
        server.receive(Packet(data=raw_ack, src=99, dst=1))
        # LAR must be unchanged
        assert server.last_ack_received == pre_lar

    def test_client_ignores_packets_from_unexpected_src(self):
        from protocol.sliding_window_sack.common import encode_sw_payload
        client = SWSACKClient(
            name=2, server=1,
            buffer_window_size=4, seq_space=64,
        )
        # Not connected to a network so receive should return before send_sack
        # Just verify the method doesn't raise and buffer stays empty.
        raw = encode_sw_payload(1, b"x")
        packet = Packet(data=raw, src=99, dst=2)
        client.receive(packet)
        assert len(client.buffer) == 0
        assert len(client.received_data) == 0

    def test_server_window_never_exceeds_window_size(self):
        """At every ACK the server window dict must stay <= window_size."""
        payload = b"window invariant" * 4

        # We instrument via a subclass to check window size on every receive.
        violations: list[int] = []

        class CheckingServer(SWSACKServer):
            def handle_ack_packet(self, ack_seq, sack_blocks):
                super().handle_ack_packet(ack_seq, sack_blocks)
                if len(self.window) > self.window_size:
                    violations.append(len(self.window))

        sim = NetworkSim(seed=42, logging=False)
        network = Network(sim)
        server = CheckingServer(
            name=1, receiver=2, data=payload,
            window_size=4, frame_size=8,
            retransmit_timeout=20, seq_space=64,
        )
        client = SWSACKClient(name=2, server=1, buffer_window_size=4, seq_space=64)
        network.add_node(server)
        network.add_node(client)
        ch = Channel(bit_rate=1000 * 8 * 100, propagation_delay=2)
        network.add_channel(ch)
        ch.add_node(server)
        ch.add_node(client)
        with redirect_stdout(StringIO()):
            sim.start()

        assert violations == [], f"Window exceeded window_size: {violations}"

    def test_last_ack_received_only_advances_monotonically(self):
        """LAR must never decrease."""
        payload = b"monotonic lar test" * 3
        lar_history: list[int] = []

        class MonotonicServer(SWSACKServer):
            def update_window(self):
                before = self.last_ack_received
                super().update_window()
                lar_history.append(self.last_ack_received)

        sim = NetworkSim(seed=5, logging=False)
        network = Network(sim)
        server = MonotonicServer(
            name=1, receiver=2, data=payload,
            window_size=4, frame_size=8,
            retransmit_timeout=20, seq_space=64,
        )
        client = SWSACKClient(name=2, server=1, buffer_window_size=4, seq_space=64)
        network.add_node(server)
        network.add_node(client)
        ch = Channel(bit_rate=1000 * 8 * 100, propagation_delay=2)
        network.add_channel(ch)
        ch.add_node(server)
        ch.add_node(client)
        with redirect_stdout(StringIO()):
            sim.start()

        for a, b in zip(lar_history, lar_history[1:]):
            # seq_dist from a to b should be positive or zero
            dist = (b - a) % server.seq_space
            assert dist <= server.window_size, f"LAR moved backwards: {a} -> {b}"

    def test_last_ack_sent_only_advances_monotonically(self):
        """Client LAS must never decrease."""
        payload = b"monotonic las test" * 3
        las_history: list[int] = []

        class MonotonicClient(SWSACKClient):
            def update_window(self):
                super().update_window()
                las_history.append(self.last_ack_sent)

        sim = NetworkSim(seed=5, logging=False)
        network = Network(sim)
        server = SWSACKServer(
            name=1, receiver=2, data=payload,
            window_size=4, frame_size=8,
            retransmit_timeout=20, seq_space=64,
        )
        client = MonotonicClient(name=2, server=1, buffer_window_size=4, seq_space=64)
        network.add_node(server)
        network.add_node(client)
        ch = Channel(bit_rate=1000 * 8 * 100, propagation_delay=2)
        network.add_channel(ch)
        ch.add_node(server)
        ch.add_node(client)
        with redirect_stdout(StringIO()):
            sim.start()

        for a, b in zip(las_history, las_history[1:]):
            dist = (b - a) % client.seq_space
            assert dist <= client.buffer_window_size, f"LAS moved backwards: {a} -> {b}"

    def test_all_received_data_length_equals_payload_length(self):
        payload = b"length invariant" * 5
        server, client, _ = _run_sim(
            payload, window_size=6, frame_size=10, seq_space=128,
        )
        assert len(client.received_data) == len(payload)

    def test_str_payload_is_correctly_transferred(self):
        server = SWSACKServer(
            name=1, receiver=2, data="hello from server",
            window_size=4, frame_size=8,
            retransmit_timeout=20, seq_space=64,
        )
        expected = "hello from server".encode("utf-8")

        sim = NetworkSim(seed=42, logging=False)
        network = Network(sim)
        client = SWSACKClient(name=2, server=1, buffer_window_size=4, seq_space=64)
        network.add_node(server)
        network.add_node(client)
        ch = Channel(bit_rate=1000 * 8 * 100, propagation_delay=2)
        network.add_channel(ch)
        ch.add_node(server)
        ch.add_node(client)
        with redirect_stdout(StringIO()):
            sim.start()

        assert bytes(client.received_data) == expected
        assert server.is_complete()
