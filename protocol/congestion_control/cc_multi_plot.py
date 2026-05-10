"""
Multi-sender congestion-control experiment.

Runs NUM_SENDERS TCPServer / TCPClient pairs sharing a single bottleneck
channel and plots:
  - Average cwnd across all senders over simulation time
  - Average RTO  across all senders over simulation time

Both graphs include a reference curve showing 2× the time-varying
propagation delay so the relationship between network conditions and
the protocol's response is immediately visible.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from src.channel import Channel
from src.network import Network
from src.network_sim import NetworkSim

from protocol.congestion_control.cc_client import TCPClient
from protocol.congestion_control.cc_server import TCPServer

# ---------------------------------------------------------------------------
# Experiment parameters
# ---------------------------------------------------------------------------

NUM_SENDERS = 20

# Sinusoidal propagation delay: oscillates between
# (BASE_DELAY_MS - AMPLITUDE_MS) and (BASE_DELAY_MS + AMPLITUDE_MS) ms
PERIOD_MS    = 4000
BASE_DELAY_MS = 16
AMPLITUDE_MS  = 10

# Shared channel
BIT_RATE       = 1000 * 8 * 1000  # 100 KB/s
QUEUE_LENGTH   = 30
DELAY_VARIANCE = 10

# Per-sender config
WINDOW_SIZE         = 50
FRAME_SIZE          = 8
SEQ_SPACE           = 512
INITIAL_RTO         = 300
MIN_RTO             = 20
MAX_RTO             = 8000
SNAPSHOT_INTERVAL   = 50
SEED                = 7

PAYLOAD = (
	b"Multi-sender congestion-control demo. "
	b"0000000000000000000000000000000000000000000000000000"
)


def propagation_delay_fn(t: float) -> float:
	return BASE_DELAY_MS + AMPLITUDE_MS * np.sin(t * 2 * np.pi / PERIOD_MS)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def run_experiment() -> tuple[list[float], list[float], int]:
	"""
	Build a network with NUM_SENDERS server/client pairs on a shared channel,
	run until completion, and return:
	  (avg_cwnd_per_snapshot, avg_rto_per_snapshot, snapshot_interval_ms)
	"""
	sim = NetworkSim(
		seed=SEED,
		logging=False,
		track_analytics=True,
		snapshot_interval=SNAPSHOT_INTERVAL,
	)
	network = Network(sim)

	# Servers have names 1 .. NUM_SENDERS
	# Clients have names NUM_SENDERS+1 .. 2*NUM_SENDERS
	for i in range(1, NUM_SENDERS + 1):
		server = TCPServer(
			name=i,
			receiver=NUM_SENDERS + i,
			data=PAYLOAD*(15*(10)),
			window_size=WINDOW_SIZE,
			frame_size=FRAME_SIZE,
			retransmit_timeout=INITIAL_RTO,
			seq_space=SEQ_SPACE,
			min_rto=MIN_RTO,
			max_rto=MAX_RTO,
		)
		client = TCPClient(
			name=NUM_SENDERS + i,
			server=i,
			buffer_window_size=WINDOW_SIZE,
			seq_space=SEQ_SPACE,
			max_sack_blocks=4,
		)
		network.add_node(server)
		network.add_node(client)

	# All senders share one bottleneck channel
	channel = Channel(
		bit_rate=BIT_RATE,
		propagation_delay=BASE_DELAY_MS,
		delay_variance=DELAY_VARIANCE,
		error_rate=0,
		max_queue_length=QUEUE_LENGTH,
		propagation_delay_fn=propagation_delay_fn,
	)
	network.add_channel(channel)
	for node in network.nodes:
		channel.add_node(node)

	# with redirect_stdout(StringIO()):
	sim.start()

	# node_analytics[t] is the element-wise sum of all nodes' snapshots at
	# snapshot t.  Server snapshot: [cwnd, cthresh, rto, srtt, svar, ss_flag]
	# Client snapshot: [0, 0, 0, 0, 0, 0]
	# So index 0 == sum of cwnd, index 2 == sum of rto across all servers.
	avg_cwnd: list[float] = []
	avg_rto:  list[float] = []

	for snap in sim.node_analytics:
		if len(snap) >= 3:
			avg_cwnd.append(snap[0] / NUM_SENDERS)
			avg_rto.append( snap[2] / NUM_SENDERS)

	return avg_cwnd, avg_rto, SNAPSHOT_INTERVAL


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot(avg_cwnd: list[float], avg_rto: list[float], window_ms: int) -> None:
	n = max(len(avg_cwnd), len(avg_rto))
	x_ms = np.array([i * window_ms for i in range(n)], dtype=float)

	# Reference: round-trip time ≈ 2 × one-way propagation delay
	rtt_ref = 2 * (BASE_DELAY_MS + AMPLITUDE_MS * np.sin(x_ms * 2 * np.pi / PERIOD_MS))

	fig, (ax_rto, ax_cwnd) = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

	fig.suptitle(
		f"TCP Congestion Control — {NUM_SENDERS} senders sharing one channel\n"
		f"(averages across all senders)",
		fontsize=13,
	)

	# --- RTO subplot ---
	ax_rto.plot(
		x_ms[: len(avg_rto)], avg_rto,
		linewidth=2, color="tab:red", label="Avg RTO",
	)
	ax_rto.plot(
		x_ms, rtt_ref,
		linestyle="--", linewidth=1.5, color="tab:gray",
		label="2 × prop delay  (reference RTT)",
	)
	ax_rto.set_title("Average Retransmit Timeout (RTO) Over Time")
	ax_rto.set_ylabel("RTO (ms)")
	ax_rto.grid(True, alpha=0.3)
	ax_rto.legend()

	# --- cwnd subplot ---
	ax_cwnd.plot(
		x_ms[: len(avg_cwnd)], avg_cwnd,
		linewidth=2, color="tab:blue", label="Avg cwnd",
	)
	ax_cwnd.set_title("Average Congestion Window (cwnd) Over Time")
	ax_cwnd.set_xlabel(
		f"Simulation time (ms)  [snapshot interval = {window_ms} ms]"
	)
	ax_cwnd.set_ylabel("cwnd (packets)")
	ax_cwnd.grid(True, alpha=0.3)
	ax_cwnd.legend()

	plt.tight_layout()

	output_path = Path(__file__).with_name("cc_multi_metrics.png")
	plt.savefig(output_path, dpi=100, bbox_inches="tight")
	plt.show()
	print(f"Plot saved to: {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
	print(
		f"Running multi-sender simulation  "
		f"({NUM_SENDERS} senders, shared channel)..."
	)
	cwnd, rto, interval = run_experiment()
	print(f"Collected {len(cwnd)} snapshots over {interval} ms intervals")
	if cwnd:
		print(f"Avg cwnd range : {min(cwnd):.1f} – {max(cwnd):.1f} packets")
	if rto:
		print(f"Avg RTO  range : {min(rto):.1f} – {max(rto):.1f} ms")
	plot(cwnd, rto, interval)
