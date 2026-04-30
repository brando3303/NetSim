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

from protocol.adaptive_timeout.at_client import ATClient
from protocol.adaptive_timeout.at_server import ATServer, _WindowEntry
from protocol.adaptive_timeout.common import (
    SackBlock,
    decode_sack_payload,
    decode_sw_payload,
    encode_sack_payload,
    encode_sw_payload,
)


class _DummyNetwork:
    def __init__(self, time: int):
        self.sim = type("_DummySim", (), {"time": time})()

    def schedule_after(self, _delay, _callback, *_args, **_kwargs):
        return None


def _run_sim(
    payload: bytes,
    *,
    window_size: int = 4,
    frame_size: int = 8,
    retransmit_timeout: int = 40,
    seq_space: int = 64,
    bit_rate: int = 1000 * 8 * 100,
    propagation_delay: int = 2,
    delay_variance: int = 0,
    error_rate: int = 0,
    seed: int = 42,
    min_rto: int = 10,
    max_rto: int = 1000,
) -> tuple[ATServer, ATClient, NetworkSim]:
    sim = NetworkSim(seed=seed, logging=False)
    network = Network(sim)

    server = ATServer(
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
    client = ATClient(
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


class TestWireFormat:
    def test_sw_payload_round_trip(self):
        encoded = encode_sw_payload(7, b"hello")
        decoded = decode_sw_payload(encoded)
        assert decoded is not None
        seq, payload = decoded
        assert seq == 7
        assert payload == b"hello"

    def test_sack_payload_round_trip(self):
        encoded = encode_sack_payload(5, [SackBlock(3, 6)])
        decoded = decode_sack_payload(encoded)
        assert decoded is not None
        ack, blocks = decoded
        assert ack == 5
        assert blocks == [SackBlock(3, 6)]


class TestAdaptiveTimeoutUnit:
    def _make_server(self) -> ATServer:
        return ATServer(
            name=1,
            receiver=2,
            data=b"payload",
            window_size=4,
            frame_size=4,
            retransmit_timeout=100,
            seq_space=32,
            min_rto=20,
            max_rto=300,
        )

    def test_update_timeout_clamps_to_min(self):
        server = self._make_server()
        server.update_timeout(0)
        assert server.retransmit_timeout >= server.min_rto

    def test_update_timeout_clamps_to_max(self):
        server = self._make_server()
        server.update_timeout(10000)
        assert server.retransmit_timeout <= server.max_rto

    def test_process_ack_updates_timeout_for_non_retransmitted_packet(self):
        server = self._make_server()
        server._network = _DummyNetwork(time=200)
        server.window[1] = _WindowEntry(
            acked=False,
            packet=Packet(b"x", 1, 2),
            time_sent=100,
            retransmitted=False,
        )

        before = server.retransmit_timeout
        server.process_ack(1)

        assert server.window[1].acked is True
        assert server.retransmit_timeout != before

    def test_process_ack_does_not_update_timeout_for_retransmitted_packet(self):
        server = self._make_server()
        server._network = _DummyNetwork(time=200)
        server.window[1] = _WindowEntry(
            acked=False,
            packet=Packet(b"x", 1, 2),
            time_sent=100,
            retransmitted=True,
        )

        before = server.retransmit_timeout
        server.process_ack(1)

        assert server.window[1].acked is True
        assert server.retransmit_timeout == before

    def test_retransmit_timer_doubles_rto_with_cap(self):
        server = self._make_server()
        server._network = _DummyNetwork(time=0)

        class _DummyChannel:
            def send(self, _packet):
                return None

        server.channels = [_DummyChannel()]
        server.window[1] = _WindowEntry(
            acked=False,
            packet=Packet(b"x", 1, 2),
            time_sent=0,
            retransmitted=False,
        )
        server.last_ack_received = 0
        server.window_size = 4

        server.retransmit_timer(1)
        assert server.window[1].retransmitted is True
        assert server.retransmit_timeout == 200

        server.retransmit_timer(1)
        assert server.retransmit_timeout == 300


class TestIntegration:
    def test_perfect_channel_delivers_exact_payload(self):
        payload = b"hello adaptive timeout"
        server, client, _ = _run_sim(payload, error_rate=0)
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_lossy_channel_still_delivers(self):
        payload = b"lossy adaptive timeout test " * 6
        server, client, _ = _run_sim(
            payload,
            error_rate=30,
            delay_variance=6,
            seed=99,
            retransmit_timeout=50,
            min_rto=10,
            max_rto=1200,
        )
        assert bytes(client.received_data) == payload
        assert server.is_complete()

    def test_rto_changes_during_variable_network_conditions(self):
        payload = b"rto adaptation test" * 12
        initial_rto = 40
        server, client, _ = _run_sim(
            payload,
            retransmit_timeout=initial_rto,
            delay_variance=20,
            propagation_delay=4,
            error_rate=10,
            seed=7,
            min_rto=10,
            max_rto=1000,
        )
        assert bytes(client.received_data) == payload
        assert server.is_complete()
        assert server.retransmit_timeout != initial_rto

    def test_server_ignores_packets_from_unexpected_src(self):
        server = ATServer(
            name=1,
            receiver=2,
            data=b"filter test",
            window_size=4,
            frame_size=4,
            retransmit_timeout=20,
            seq_space=64,
        )
        before = server.last_ack_received
        server.receive(Packet(data=encode_sack_payload(1, []), src=99, dst=1))
        assert server.last_ack_received == before


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
