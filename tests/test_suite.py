from __future__ import annotations

import pytest

from src.channel import BROADCAST_ID, Channel
from src.network import Network
from src.network_sim import NetworkSim
from src.node import Node
from src.packet import Packet, decode_packet, encode_packet, validate


class RecordingNode(Node):
    def __init__(self, name: int):
        super().__init__(name)
        self.init_called = 0
        self.start_called = 0
        self.received: list[Packet] = []

    def init(self):
        self.init_called += 1

    def start(self):
        self.start_called += 1

    def receive(self, packet: Packet):
        self.received.append(packet)


class SenderNode(RecordingNode):
    def __init__(self, name: int, payload: str, dst: int):
        super().__init__(name)
        self.payload = payload
        self.dst = dst

    def start(self):
        super().start()
        self.channels[0].send(Packet(self.payload, self.name, self.dst))


def build_basic_topology(
    *,
    seed: int = 42,
    bit_rate: int = 1000 * 8,
    prop_delay: int = 0,
    error_rate: float = 0,
    average_error: int = 0,
) -> tuple[NetworkSim, Network, Channel, RecordingNode, RecordingNode]:
    sim = NetworkSim(seed=seed, logging=False)
    network = Network(sim)

    node1 = RecordingNode(1)
    node2 = RecordingNode(2)
    network.add_node(node1)
    network.add_node(node2)

    channel = Channel(
        bit_rate=bit_rate,
        propogation_delay=prop_delay,
        error_rate=int(error_rate),
        average_error=average_error,
    )
    network.add_channel(channel)
    channel.add_node(node1)
    channel.add_node(node2)

    return sim, network, channel, node1, node2


def test_packet_round_trip_string_payload_preserves_fields_and_validates():
    packet = Packet("hello", 101, 202)

    raw = encode_packet(packet)
    decoded = decode_packet(raw)

    assert decoded.src == 101
    assert decoded.dst == 202
    assert decoded.data == "hello"
    assert validate(raw) is True


def test_packet_round_trip_binary_payload_preserves_bytes():
    payload = bytes([0, 1, 2, 250, 255])
    packet = Packet(payload, 101, 202)

    raw = encode_packet(packet)
    decoded = decode_packet(raw)

    assert decoded.data == payload
    assert validate(raw) is True


def test_packet_validate_fails_after_payload_tamper():
    packet = Packet("hello", 101, 202)
    raw = bytearray(encode_packet(packet))

    # Flip one byte in the payload, leaving the header checksum unchanged.
    raw[-5] ^= 0x01

    assert validate(bytes(raw)) is False


def test_networksim_rejects_invalid_scheduling_inputs():
    sim = NetworkSim(seed=1)

    with pytest.raises(ValueError, match="Delay must be non-negative"):
        sim.schedule_after(-1, lambda: None)

    sim.time = 10
    with pytest.raises(ValueError, match="Cannot schedule events in the past"):
        sim.schedule_at(9, lambda: None)


def test_network_requires_at_least_one_node_for_init():
    sim = NetworkSim(seed=1)
    network = Network(sim)

    with pytest.raises(RuntimeError, match="at least one node"):
        network.init()


def test_network_start_requires_init_first():
    sim = NetworkSim(seed=1)
    network = Network(sim)
    network.add_node(RecordingNode(1))

    with pytest.raises(RuntimeError, match="initialized before starting"):
        network.start()


def test_send_respects_channel_queue_limit_and_drops_extra_packets():
    sim, network, channel, _n1, _n2 = build_basic_topology()

    limited_channel = Channel(max_queue_length=1, bit_rate=channel.bit_rate, propogation_delay=0)
    network.add_channel(limited_channel)
    limited_channel.add_node(_n1)
    limited_channel.add_node(_n2)

    limited_channel.send(Packet("first", 1, 2))
    limited_channel.send(Packet("second", 1, 2))

    assert len(limited_channel.packet_queue) == 1
    assert len(sim.eventQueue) == 1


def test_channel_snapshot_counts_drops_for_queue_overflow():
    sim, network, channel, n1, n2 = build_basic_topology()

    limited_channel = Channel(
        max_queue_length=1,
        bit_rate=channel.bit_rate,
        propogation_delay=0,
    )
    network.add_channel(limited_channel)
    limited_channel.add_node(n1)
    limited_channel.add_node(n2)

    limited_channel.send(Packet("first", 1, 2))
    limited_channel.send(Packet("second", 1, 2))

    assert limited_channel.snapshot() == [0, 1]


def test_channel_snapshot_counts_drops_for_corrupt_packets():
    sim, _network, channel, _n1, _n2 = build_basic_topology(error_rate=1.0, average_error=2)

    channel.handle_receive_packet(encode_packet(Packet("hello", 1, 2)))
    channel.handle_receive_packet(encode_packet(Packet("hello", 1, 2)))

    assert channel.snapshot() == [0, 2]


def test_channel_snapshot_resets_counters():
    sim, _network, channel, _n1, _n2 = build_basic_topology(error_rate=1.0, average_error=2)

    channel.handle_receive_packet(encode_packet(Packet("hello", 1, 2)))
    channel.snapshot()  # consume and reset

    assert channel.snapshot() == [0, 0]


def test_channel_snapshot_counts_throughput_for_unicast():
    sim, _network, channel, _n1, _n2 = build_basic_topology(error_rate=0.0)

    channel.handle_receive_packet(encode_packet(Packet("hello", 1, 2)))
    channel.handle_receive_packet(encode_packet(Packet("hello", 1, 2)))

    assert channel.snapshot() == [2, 0]


def test_channel_snapshot_counts_throughput_for_broadcast_once_per_packet():
    sim = NetworkSim(seed=42, logging=False)
    network = Network(sim)

    n1 = RecordingNode(1)
    n2 = RecordingNode(2)
    n3 = RecordingNode(3)
    network.add_node(n1)
    network.add_node(n2)
    network.add_node(n3)

    channel = Channel(
        bit_rate=1000 * 8,
        propogation_delay=0,
        error_rate=0,
    )
    network.add_channel(channel)
    channel.add_node(n1)
    channel.add_node(n2)
    channel.add_node(n3)

    channel.handle_receive_packet(encode_packet(Packet("broadcast", 1, BROADCAST_ID)))

    assert channel.snapshot() == [1, 0]


def test_channel_delivers_when_packet_is_valid():
    _sim, _network, channel, n1, n2 = build_basic_topology()
    packet_bytes = encode_packet(Packet("ok", 1, 2))

    channel.handle_receive_packet(packet_bytes)

    assert len(n1.received) == 0
    assert len(n2.received) == 1


def test_channel_drops_corrupted_packet_when_error_injection_triggers():
    _sim, _network, channel, n1, n2 = build_basic_topology(error_rate=1.0, average_error=2)
    packet_bytes = encode_packet(Packet("hello", 1, 2))

    channel.handle_receive_packet(packet_bytes)

    assert len(n1.received) == 0
    assert len(n2.received) == 0


def test_packet_equality_respects_fields():
    assert Packet("a", 1, 2) != Packet("b", 1, 2)
    assert Packet("a", 1, 2) != Packet("a", 2, 1)


def test_packet_rejects_out_of_range_addresses():
    with pytest.raises(ValueError, match="range"):
        encode_packet(Packet("hello", -1, 2))

    with pytest.raises(ValueError, match="range"):
        encode_packet(Packet("hello", 1, 2**32))


def test_packet_wire_format_is_src_dst_checksum_payload():
    packet = Packet("abc", 1, 2)
    raw = encode_packet(packet)

    # Header is src(4), dst(4), checksum(4), then payload.
    assert len(raw) >= 13
    assert raw[12] in (0, 1)


def test_event_ordering_does_not_compare_callbacks_when_times_match():
    sim = NetworkSim(seed=1)
    observed: list[int] = []

    sim.schedule_at(5, lambda: observed.append(1))
    sim.schedule_at(5, lambda: observed.append(2))

    sim.running = True
    sim.simulation_loop()

    assert observed == [1, 2]


def test_channel_drops_malformed_packet_bytes_without_raising():
    _sim, _network, channel, n1, n2 = build_basic_topology()

    channel.handle_receive_packet(b"bad")

    assert len(n1.received) == 0
    assert len(n2.received) == 0


def test_full_simulation_start_init_and_delivery_flow():
    sim = NetworkSim(seed=42, logging=False)
    network = Network(sim)

    sender = SenderNode(1, payload="Hello", dst=2)
    receiver = RecordingNode(2)
    network.add_node(sender)
    network.add_node(receiver)

    channel = Channel(bit_rate=1000 * 8, propogation_delay=0, error_rate=0)
    network.add_channel(channel)
    channel.add_node(sender)
    channel.add_node(receiver)

    sim.start()

    assert sender.init_called == 1
    assert receiver.init_called == 1
    assert sender.start_called == 1
    assert receiver.start_called == 1
    assert len(sender.received) == 0
    assert len(receiver.received) == 1
    assert receiver.received[0].data == "Hello"


def test_design_doc_destination_only_delivery_requirement():
    _sim, _network, channel, n1, n2 = build_basic_topology()

    channel.handle_receive_packet(encode_packet(Packet("to node2", 1, 2)))

    assert len(n1.received) == 0
    assert len(n2.received) == 1


def test_broadcast_delivers_to_all_nodes_except_source():
    sim = NetworkSim(seed=42, logging=False)
    network = Network(sim)

    n1 = RecordingNode(1)
    n2 = RecordingNode(2)
    n3 = RecordingNode(3)
    network.add_node(n1)
    network.add_node(n2)
    network.add_node(n3)

    channel = Channel(bit_rate=1000 * 8, propogation_delay=0, error_rate=0)
    network.add_channel(channel)
    channel.add_node(n1)
    channel.add_node(n2)
    channel.add_node(n3)

    channel.handle_receive_packet(encode_packet(Packet("broadcast", 1, BROADCAST_ID)))

    assert len(n1.received) == 0
    assert len(n2.received) == 1
    assert len(n3.received) == 1
    assert n2.received[0].data == "broadcast"
    assert n3.received[0].data == "broadcast"


def test_broadcast_drops_when_error_injection_corrupts_packet():
    sim = NetworkSim(seed=42, logging=False)
    network = Network(sim)

    n1 = RecordingNode(1)
    n2 = RecordingNode(2)
    n3 = RecordingNode(3)
    network.add_node(n1)
    network.add_node(n2)
    network.add_node(n3)

    channel = Channel(bit_rate=1000 * 8, propogation_delay=0, error_rate=1, average_error=2)
    network.add_channel(channel)
    channel.add_node(n1)
    channel.add_node(n2)
    channel.add_node(n3)

    channel.handle_receive_packet(encode_packet(Packet("broadcast", 1, BROADCAST_ID)))

    assert len(n1.received) == 0
    assert len(n2.received) == 0
    assert len(n3.received) == 0
