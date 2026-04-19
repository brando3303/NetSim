from __future__ import annotations

import pytest

from src.channel import Channel
from src.network import Network
from src.network_sim import NetworkSim
from src.node import Node
from src.packet import Packet


class RecordingNode(Node):
    def __init__(self, name: str):
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
    def __init__(self, name: str, payload: str, dst: str):
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

    node1 = RecordingNode("Node 1")
    node2 = RecordingNode("Node 2")
    network.add_node(node1)
    network.add_node(node2)

    channel = Channel(
        bitRate=bit_rate,
        propogationDelay=prop_delay,
        errorRate=int(error_rate),
        averageError=average_error,
    )
    network.add_channel(channel)
    channel.add_node(node1)
    channel.add_node(node2)

    return sim, network, channel, node1, node2


def test_packet_round_trip_string_payload_preserves_fields_and_validates():
    packet = Packet("hello", "A", "B")

    raw = packet.to_bytes()
    decoded = Packet.from_bytes(raw)

    assert decoded.src == "A"
    assert decoded.dst == "B"
    assert decoded.data == "hello"
    assert decoded.validate() is True


def test_packet_round_trip_binary_payload_preserves_bytes():
    payload = bytes([0, 1, 2, 250, 255])
    packet = Packet(payload, "A", "B")

    decoded = Packet.from_bytes(packet.to_bytes())

    assert decoded.data == payload
    assert decoded.validate() is True


def test_packet_validate_fails_after_payload_tamper():
    packet = Packet("hello", "A", "B")
    raw = bytearray(packet.to_bytes())

    # Flip one byte in the packet body, leaving the appended CRC unchanged.
    raw[-5] ^= 0x01

    decoded = Packet.from_bytes(bytes(raw))
    assert decoded.validate() is False


def test_networksim_rejects_invalid_scheduling_inputs():
    sim = NetworkSim(seed=1)

    with pytest.raises(Exception, match="Delay must be non-negative"):
        sim.schedule_after(-1, lambda: None)

    sim.time = 10
    with pytest.raises(Exception, match="Cannot schedule events in the past"):
        sim.schedule_at(9, lambda: None)


def test_network_requires_at_least_one_node_for_init():
    sim = NetworkSim(seed=1)
    network = Network(sim)

    with pytest.raises(Exception, match="at least one node"):
        network.init()


def test_network_start_requires_init_first():
    sim = NetworkSim(seed=1)
    network = Network(sim)
    network.add_node(RecordingNode("only"))

    with pytest.raises(Exception, match="initialized before starting"):
        network.start()


def test_send_respects_channel_queue_limit_and_drops_extra_packets():
    sim, network, channel, _n1, _n2 = build_basic_topology()

    limited_channel = Channel(maxQueueLength=1, bitRate=channel.bitRate, propogationDelay=0)
    network.add_channel(limited_channel)
    limited_channel.add_node(_n1)
    limited_channel.add_node(_n2)

    limited_channel.send(Packet("first", "Node 1", "Node 2"))
    limited_channel.send(Packet("second", "Node 1", "Node 2"))

    assert len(limited_channel.packetQueue) == 1
    assert len(sim.eventQueue) == 1


def test_channel_delivers_when_packet_is_valid():
    _sim, _network, channel, n1, n2 = build_basic_topology()
    packet_bytes = Packet("ok", "Node 1", "Node 2").to_bytes()

    channel.handle_receive_packet(packet_bytes)

    assert len(n1.received) == 0
    assert len(n2.received) == 1


def test_channel_drops_corrupted_packet_when_error_injection_triggers():
    _sim, _network, channel, n1, n2 = build_basic_topology(error_rate=1.0, average_error=2)
    packet_bytes = Packet("hello", "Node 1", "Node 2").to_bytes()

    channel.handle_receive_packet(packet_bytes)

    assert len(n1.received) == 0
    assert len(n2.received) == 0


def test_channel_drops_malformed_packet_bytes_without_raising():
    _sim, _network, channel, n1, n2 = build_basic_topology()

    channel.handle_receive_packet(b"bad")

    assert len(n1.received) == 0
    assert len(n2.received) == 0


def test_full_simulation_start_init_and_delivery_flow():
    sim = NetworkSim(seed=42, logging=False)
    network = Network(sim)

    sender = SenderNode("Node 1", payload="Hello", dst="Node 2")
    receiver = RecordingNode("Node 2")
    network.add_node(sender)
    network.add_node(receiver)

    channel = Channel(bitRate=1000 * 8, propogationDelay=0, errorRate=0)
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

    channel.handle_receive_packet(Packet("to node2", "Node 1", "Node 2").to_bytes())

    assert len(n1.received) == 0
    assert len(n2.received) == 1
