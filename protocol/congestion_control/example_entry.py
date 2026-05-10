"""TCP-like congestion-control demo.

Demonstrates :class:`~protocol.congestion_control.cc_server.TCPServer`
transferring a large payload over a channel with sinusoidal propagation delay
and a finite-length queue.  Run this file directly to see the transfer summary.
Run ``cc_plot.py`` to visualise how the congestion window and RTO evolve.

Background
----------
The adaptive-timeout protocol from ``protocol/adaptive_timeout/`` keeps the
window size **fixed**.  This works well on a quiet link, but on a shared
network the sender has no idea how many other flows are competing for the same
bottleneck queue.  Sending at a fixed rate causes the queue to overflow and
packets to be dropped, and the only feedback the sender gets is silence (no
ACK for a retransmit timeout).

:class:`~protocol.congestion_control.cc_server.TCPServer` adds a **congestion
window** (``cwnd``) that the sender grows or shrinks based on ACK feedback:

* **Slow start** — ``cwnd`` begins at 1 frame and *doubles* each round-trip
  (one extra frame per ACK) until it hits ``congestion_threshold``.  This
  probes for available bandwidth quickly without immediately flooding the link.

* **AIMD additive increase** — Once past the threshold, ``cwnd`` grows by one
  frame per full window's worth of ACKs (linear growth).

* **Multiplicative decrease** — Any congestion signal (triple duplicate ACK or
  RTO) halves ``congestion_threshold`` and resets ``cwnd``.  This backs off
  aggressively when the network signals distress.

* **Fast retransmit / fast recovery** — Three consecutive duplicate ACKs
  trigger an immediate retransmit without waiting for the timer.  The
  connection then stays in AIMD mode rather than re-entering slow start,
  so throughput recovers quickly.

* **Adaptive RTO** — Same Jacobson/Karels SRTT/SVAR algorithm as the
  adaptive-timeout protocol.

The finite ``max_queue_length`` on the channel below means the bottleneck
queue *will* occasionally drop packets when ``cwnd`` overshoots, letting
the congestion-control loop react and demonstrating realistic AIMD sawtooth
behaviour.
"""
from __future__ import annotations

from pathlib import Path
import sys

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
# Tunable parameters
# ---------------------------------------------------------------------------

#: Size of the sequence-number space.  Must satisfy ``WINDOW_SIZE < SEQ_SPACE // 2``.
SEQ_SPACE = 1024

#: Hard ceiling on frames in flight.  The effective sending window is
#: ``min(cwnd, WINDOW_SIZE)``, so cwnd can grow up to this value.
WINDOW_SIZE = 300

#: Maximum payload bytes per data frame.
FRAME_SIZE = 8

#: Initial RTO before the first RTT sample is collected (ms).
INITIAL_RTO = 500

#: Hard lower bound on the computed RTO (ms).
MIN_RTO = 20

#: Hard upper bound on the computed RTO (ms).
MAX_RTO = 10_000

#: Channel transmission rate in bits per second.
BIT_RATE = 1_000 * 8 * 100  # 800 kbps

#: Maximum number of frames the channel's transmit queue can hold.
#: When the queue is full, arriving frames are dropped — this is what
#: triggers the multiplicative-decrease half of AIMD.
MAX_QUEUE_LENGTH = 30

#: How often the simulator records an analytics snapshot (ms).
SNAPSHOT_INTERVAL = 50

# ---------------------------------------------------------------------------
# Propagation-delay function
# ---------------------------------------------------------------------------
# The one-way delay oscillates between 10 ms and 30 ms with a 4-second period,
# modelling gentle path variation.  The short delays let cwnd grow large enough
# for congestion-control dynamics to be visible without a very long simulation.

_PERIOD_MS = 4_000
_BASE_DELAY_MS = 20
_AMPLITUDE_MS = 10


def propagation_delay_fn(t: float) -> float:
	"""Return the one-way propagation delay (ms) at simulator time *t* (ms)."""
	return _BASE_DELAY_MS + _AMPLITUDE_MS * np.sin(t * 2 * np.pi / _PERIOD_MS)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main() -> tuple[NetworkSim, int]:
	"""Run the congestion-control demo and print a results summary.

	Returns:
		``(sim, SNAPSHOT_INTERVAL)`` so that ``cc_plot.py`` can read the
		analytics without re-running the simulation.
	"""
	payload = (
		b"Congestion-control demo payload. "
		b"This block will be reconstructed byte-for-byte at the receiver. "
		+ b"0" * 200
	) * 100

	sim = NetworkSim(
		seed=44,
		logging=False,
		track_analytics=True,
		snapshot_interval=SNAPSHOT_INTERVAL,
	)
	network = Network(sim)

	# Node 1 is the sender; node 2 is the receiver.
	server = TCPServer(
		name=1,
		receiver=2,
		data=payload,
		window_size=WINDOW_SIZE,
		frame_size=FRAME_SIZE,
		retransmit_timeout=INITIAL_RTO,
		seq_space=SEQ_SPACE,
		min_rto=MIN_RTO,
		max_rto=MAX_RTO,
	)
	client = TCPClient(
		name=2,
		server=1,
		buffer_window_size=WINDOW_SIZE,
		seq_space=SEQ_SPACE,
		max_sack_blocks=4,
	)

	network.add_node(server)
	network.add_node(client)

	channel = Channel(
		bit_rate=BIT_RATE,
		propagation_delay=_BASE_DELAY_MS,
		delay_variance=2,
		error_rate=0,
		max_queue_length=MAX_QUEUE_LENGTH,
		propagation_delay_fn=propagation_delay_fn,
	)
	network.add_channel(channel)
	channel.add_node(server)
	channel.add_node(client)

	sim.start()

	reconstructed = bytes(client.received_data)
	print(f"\nDelivered bytes         : {len(reconstructed)}")
	print(f"Expected bytes          : {len(payload)}")
	print(f"Server complete         : {server.is_complete()}")
	print(f"Payload matches         : {reconstructed == payload}")
	print(f"Sim time elapsed        : {sim.time} ms")
	print(f"Final cwnd              : {server.congestion_window} frames")
	print(f"Final ssthresh          : {server.congestion_threshold} frames")
	print(f"Final RTO               : {server.retransmit_timeout} ms")
	print(f"Final SRTT              : {int(server.smoothed_rtt)} ms")
	print(f"Analytics snapshots     : {len(sim.node_analytics)}")
	print(f"\n(Run cc_plot.py to visualise the cwnd/RTO traces.)")

	return sim, SNAPSHOT_INTERVAL


if __name__ == "__main__":
	main()
