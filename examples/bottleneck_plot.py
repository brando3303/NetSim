from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

PLOT_OUTPUT = Path(__file__).with_name("bottleneck_histogram.png")


from bottleneck import BottleneckNode, NODE_COUNT, SEND_INTERVAL_MS, TARGET_RECEIVES
from src.index import Channel, Network, NetworkSim


SNAPSHOT_INTERVAL_MS = 100
LOW_BIT_RATE = 1000 * 8 * 35
QUEUE_LENGTH = 12


def _build_histogram_x(bucket_count: int, window_ms: int) -> list[int]:
	return [i * window_ms for i in range(bucket_count)]


def _pad_histograms(*series: list[int]) -> list[list[int]]:
	max_len = max((len(s) for s in series), default=0)
	padded: list[list[int]] = []
	for s in series:
		padded.append(s + [0] * (max_len - len(s)))
	return padded


def run_histogram_experiment() -> tuple[list[int], list[int], int]:
	sim = NetworkSim(seed=13, logging=False, track_analytics=True, snapshot_interval=SNAPSHOT_INTERVAL_MS)
	net = Network(sim)
	ch = Channel(
		max_queue_length=QUEUE_LENGTH,
		bit_rate=LOW_BIT_RATE,
		propagation_delay=2,
		error_rate=0,
		average_error=0,
		delay_variance=0,
	)
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

	# channel_analytics: list of snapshots; each snapshot is a list of [throughput, drops] per channel
	# ch is the only channel (index 0)
	throughput = [snap[0] for snap in sim.channel_analytics]
	drops = [snap[1] for snap in sim.channel_analytics]
	return drops, throughput, SNAPSHOT_INTERVAL_MS


def plot_histograms(drops: list[int], throughput: list[int]) -> None:
	drops, throughput = _pad_histograms(drops, throughput)
	x = _build_histogram_x(len(drops), SNAPSHOT_INTERVAL_MS)

	plt.figure(figsize=(13, 7))
	plt.plot(x, drops, marker="o", linewidth=2, label=f"Dropped packets / {SNAPSHOT_INTERVAL_MS} ms")
	plt.plot(x, throughput, marker="s", linewidth=2, label=f"Throughput packets / {SNAPSHOT_INTERVAL_MS} ms")

	plt.title("Bottleneck Channel Histogram: Drops vs Throughput")
	plt.xlabel(f"Simulation time (ms)")
	plt.ylabel("Packets per window")
	plt.grid(True, alpha=0.3)
	plt.legend()
	plt.tight_layout()
	plt.savefig(PLOT_OUTPUT, dpi=150)

	plt.show()


def main() -> None:
	drops, throughput, window_ms = run_histogram_experiment()
	print(f"Drop histogram ({window_ms}ms): {drops}")
	print(f"Throughput histogram ({window_ms}ms): {throughput}")
	plot_histograms(drops, throughput)


if __name__ == "__main__":
	main()
