from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from protocol.congestion_control.example_entry import (
	AMPLITUDE_MS,
	BASE_DELAY_MS,
	PERIOD_MS,
	main,
)


def _x_axis(bucket_count: int, window_ms: int) -> list[int]:
	return [i * window_ms for i in range(bucket_count)]


def run_experiment() -> tuple[list[int], list[int], int]:
	"""Run the simulation and return (cwnd_values, rto_values, snapshot_interval)."""
	sim, snapshot_interval = main()

	# server snapshot layout: [cwnd, cthresh, rto, srtt, svar, in_slow_start]
	# client snapshot layout: [0, 0, 0, 0, 0, 0]
	# sum_analytics_matrix adds them, so index 0 == cwnd, index 2 == rto.
	cwnd_values: list[int] = []
	rto_values: list[int] = []

	for snap in sim.node_analytics:
		if len(snap) >= 3:
			cwnd_values.append(snap[0])
			rto_values.append(snap[2])

	return cwnd_values, rto_values, snapshot_interval


def plot(cwnd_values: list[int], rto_values: list[int], window_ms: int) -> None:
	x = _x_axis(len(cwnd_values), window_ms)
	x_rto = _x_axis(len(rto_values), window_ms)

	# Reference propagation delay curve (round-trip = 2× one-way)
	x_np = np.array(x if x else x_rto, dtype=float)
	prop_delay = BASE_DELAY_MS + AMPLITUDE_MS * np.sin(x_np * 2 * np.pi / PERIOD_MS)
	rtt_ref = 2 * prop_delay  # approximate minimum RTT visible to the sender

	fig, (ax_rto, ax_cwnd) = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

	# --- RTO plot ---
	ax_rto.plot(x_rto, rto_values, linewidth=2, color="tab:red", label="RTO")
	ax_rto.plot(
		x_np,
		rtt_ref,
		linestyle="--",
		linewidth=1.5,
		color="tab:gray",
		label=f"2 × prop delay (reference RTT)",
	)
	ax_rto.set_title("Adaptive Retransmit Timeout (RTO) Over Time")
	ax_rto.set_ylabel("RTO (ms)")
	ax_rto.grid(True, alpha=0.3)
	ax_rto.legend()

	# --- cwnd plot ---
	ax_cwnd.plot(x, cwnd_values, linewidth=2, color="tab:blue", label="cwnd")
	ax_cwnd.set_title("Congestion Window (cwnd) Over Time")
	ax_cwnd.set_xlabel(f"Simulation time (ms)  [snapshot interval = {window_ms} ms]")
	ax_cwnd.set_ylabel("cwnd (packets)")
	ax_cwnd.grid(True, alpha=0.3)
	ax_cwnd.legend()

	plt.tight_layout()

	output_path = Path(__file__).with_name("cc_metrics.png")
	plt.savefig(output_path, dpi=100, bbox_inches="tight")
	plt.show()
	print(f"Plot saved to: {output_path}")


if __name__ == "__main__":
	print("Running congestion-control simulation with analytics collection...")
	cwnd, rto, window = run_experiment()
	print(f"Collected {len(cwnd)} snapshots over {window} ms intervals")
	if cwnd:
		print(f"cwnd range : {min(cwnd)} – {max(cwnd)}")
	if rto:
		print(f"RTO range  : {min(rto)} – {max(rto)} ms")
	plot(cwnd, rto, window)
