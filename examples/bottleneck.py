from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import sys

import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.index import Channel, Network, NetworkSim, Node, Packet


TARGET_RECEIVES = 100
NODE_COUNT = 30
SEND_INTERVAL_MS = 10
QUEUE_LENGTHS = list(range(10, 60, 5))

PAYLOAD_FORMAT = "!BI"
PAYLOAD_KIND_DATA = 0
PAYLOAD_KIND_ACK = 1


@dataclass
class RunResult:
    queue_length: int
    completion_times: dict[int, int]


class BottleneckNode(Node):
    def __init__(
        self,
        node_id: int,
        next_node_id: int,
        target_receives: int,
        send_interval_ms: int,
    ):
        super().__init__(node_id)
        self.next_node_id = next_node_id
        self.target_receives = target_receives
        self.send_interval_ms = send_interval_ms
        self.received_count = 0
        self.completion_time: int | None = None
        self.next_send_seq = 1
        self.awaiting_ack = False
        self.expected_recv_seq = 1
        self.min_send_interval_ms = max(1, send_interval_ms)
        self.max_send_interval_ms = self.min_send_interval_ms * 4

    def init(self):
        return None

    def start(self):
        # Start stop-and-wait transmission to node n+1.
        self.set_timer(0, self._transmit_tick)

    def _build_payload(self, kind: int, seq_num: int) -> bytes:
        return struct.pack(PAYLOAD_FORMAT, kind, seq_num)

    def _parse_payload(self, payload: bytes) -> tuple[int, int] | None:
        if not isinstance(payload, bytes):
            return None
        if len(payload) != struct.calcsize(PAYLOAD_FORMAT):
            return None
        return struct.unpack(PAYLOAD_FORMAT, payload)

    def _transmit_tick(self):
        if self.next_send_seq > self.target_receives:
            return

        payload = self._build_payload(PAYLOAD_KIND_DATA, self.next_send_seq)
        self.channels[0].send(Packet(payload, self.name, self.next_node_id))
        self.awaiting_ack = True
        next_interval_ms = self._send_interval_for_time(self.network.sim.time)
        self.set_timer(next_interval_ms, self._transmit_tick)

    def _send_interval_for_time(self, sim_time_ms: int) -> int:
        # Triangle profile centered at 1000 ms:
        # slow start -> fastest at 1000 ms -> slow again afterwards.
        ramp_distance_ms = 3000
        distance_from_peak = abs(sim_time_ms - 3000)
        normalized = min(1.0, distance_from_peak / ramp_distance_ms)
        interval = self.min_send_interval_ms + (
            self.max_send_interval_ms - self.min_send_interval_ms
        ) * normalized
        return max(1, int(round(interval)))

    def receive(self, packet: Packet):
        if not isinstance(packet.data, bytes):
            return

        parsed = self._parse_payload(packet.data)
        if parsed is None:
            return

        kind, seq_num = parsed

        if kind == PAYLOAD_KIND_DATA:
            # ACK every in-order or duplicate data frame so sender can progress.
            if seq_num == self.expected_recv_seq:
                self.received_count += 1
                self.expected_recv_seq += 1
                if self.received_count == self.target_receives:
                    self.completion_time = self.network.sim.time
                    self._stop_sim_if_all_nodes_done()

            if seq_num < self.expected_recv_seq:
                ack_payload = self._build_payload(PAYLOAD_KIND_ACK, seq_num)
                self.channels[0].send(Packet(ack_payload, self.name, packet.src))
            return

        if kind == PAYLOAD_KIND_ACK and self.awaiting_ack and seq_num == self.next_send_seq:
            self.awaiting_ack = False
            self.next_send_seq += 1

    def _stop_sim_if_all_nodes_done(self):
        for node in self.network.nodes:
            if not isinstance(node, BottleneckNode):
                continue
            if node.received_count < self.target_receives:
                return
        self.network.sim.stop()


def run_single_experiment(queue_length: int) -> RunResult:
    sim = NetworkSim(seed=42, logging=False)
    net = Network(sim)
    ch = Channel(
        max_queue_length=queue_length,
        bit_rate=1000 * 8 * 60,
        propagation_delay=1,
        error_rate=0,
        average_error=0,
        delay_variance=0,
    )

    print(f"Running experiment with queue_length={queue_length}")
    net.add_channel(ch)

    for node_id in range(1, NODE_COUNT + 1):
        next_node_id = 1 if node_id == NODE_COUNT else node_id + 1
        node = BottleneckNode(
            node_id=node_id,
            next_node_id=next_node_id,
            target_receives=TARGET_RECEIVES,
            send_interval_ms=SEND_INTERVAL_MS,
        )
        net.add_node(node)
        ch.add_node(node)

    sim.start()

    completion_times: dict[int, int] = {}
    for node in net.nodes:
        if isinstance(node, BottleneckNode) and node.completion_time is not None:
            completion_times[node.name] = node.completion_time

    return RunResult(queue_length=queue_length, completion_times=completion_times)


def plot_results(results: list[RunResult]):
    x = [r.queue_length for r in results]
    y = [max(r.completion_times.values()) for r in results]

    plt.figure(figsize=(12, 7))
    plt.plot(x, y, marker="o", linewidth=2)

    plt.title(f"Channel Queue Length vs Max Time to Reach {TARGET_RECEIVES} Receives")
    plt.xlabel("Channel maxQueueLength (packets)")
    plt.ylabel("Max simulation time across nodes (ms)")
    plt.xlim(QUEUE_LENGTHS[0], QUEUE_LENGTHS[-1])
    plt.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def main():
    results = [run_single_experiment(q_len) for q_len in QUEUE_LENGTHS]

    print("QueueLength, NodeID, TimeTo100Receives(ms)")
    for run in results:
        for node_id in sorted(run.completion_times):
            print(f"{run.queue_length}, {node_id}, {run.completion_times[node_id]}")

    plot_results(results)


if __name__ == "__main__":
    main()
