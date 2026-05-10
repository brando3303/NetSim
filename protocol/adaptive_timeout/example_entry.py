"""Adaptive-timeout SACK demo.

Demonstrates :class:`~protocol.adaptive_timeout.at_server.ATServer` sending a
payload over a channel whose propagation delay oscillates sinusoidally.  The
sender's RTO (retransmit timeout) adapts in real-time using the
Jacobson/Karels algorithm so that retransmissions stay responsive without
constantly over-shooting or under-shooting the true round-trip time.

Run this file directly to see the transfer summary.
Run ``rto_plot.py`` to visualise how the RTO, SRTT, and SVAR traces track
the changing delay.

Background
----------
The *sliding-window + SACK* protocol from ``protocol/sliding_window_sack/``
uses a **fixed** retransmit timeout chosen at start-up.  If the real RTT
changes (congested network, variable satellite link, etc.) a fixed RTO either
fires too early (spurious retransmits waste bandwidth) or too late (slow
recovery after loss).

:class:`~protocol.adaptive_timeout.at_server.ATServer` solves this by keeping
two running statistics, updated each time a clean (non-retransmitted) ACK
arrives:

* **SRTT** — smoothed RTT, an exponential moving average of measured RTTs.
* **SVAR** — smoothed mean deviation, a measure of RTT variability.

The RTO is then set to ``SRTT + 4 * SVAR``, which gives a margin that shrinks
when the path is stable and widens when it becomes erratic.  The RTO is
clamped to ``[MIN_RTO, MAX_RTO]`` to prevent runaway values.

Additionally, if the same cumulative ACK is received **three times in a row**
the sender triggers a **fast retransmit** of the oldest unacknowledged frame
immediately, without waiting for the timer to expire.
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

from protocol.adaptive_timeout.at_client import ATClient
from protocol.adaptive_timeout.at_server import ATServer

# ---------------------------------------------------------------------------
# Tunable parameters
# ---------------------------------------------------------------------------

#: Size of the sequence-number space.  Must satisfy ``WINDOW_SIZE < SEQ_SPACE // 2``.
SEQ_SPACE = 1024

#: Maximum number of unacknowledged frames in flight simultaneously.
WINDOW_SIZE = 10

#: Maximum payload bytes carried by a single data frame.
FRAME_SIZE = 16

#: Initial RTO before the first RTT sample is collected (ms).
#: The adaptive algorithm replaces this quickly once ACKs arrive.
INITIAL_RTO = 1000

#: Hard lower bound on the computed RTO (ms).  Prevents the RTO from becoming
#: so small that a momentary delay spike causes a cascade of spurious retransmits.
MIN_RTO = 100

#: Hard upper bound on the computed RTO (ms), same as TCP
MAX_RTO = 60_000

#: Channel transmission rate in bits per second.
BIT_RATE = 1_000 * 8 * 100  # 800 kbps

#: How often the simulator records an analytics snapshot (ms).
#: Smaller values give finer RTO traces in rto_plot.py at the cost of more memory.
SNAPSHOT_INTERVAL = 10

# ---------------------------------------------------------------------------
# Propagation-delay function
# ---------------------------------------------------------------------------
# The one-way delay oscillates between ~10 ms and ~150 ms with a period of
# 1 000 ms, modelling a path that varies significantly over time (e.g. a
# satellite hop with varying queue depth).  The adaptive RTO should track
# this variation and stay just above the actual RTT (≈ 2 × one-way delay).

_DELAY_PERIOD_MS = 1_000
_DELAY_AMPLITUDE_MS = 70
_DELAY_BASE_MS = 80  # RTT oscillates between ~20 ms and ~300 ms


def propagation_delay_fn(t: float) -> float:
    """Return the one-way propagation delay (ms) at simulator time *t* (ms)."""
    return _DELAY_BASE_MS + _DELAY_AMPLITUDE_MS * np.sin(t * 2 * np.pi / _DELAY_PERIOD_MS)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main() -> tuple[NetworkSim, int]:
    """Run the adaptive-timeout demo and print a results summary.

    Returns:
        ``(sim, SNAPSHOT_INTERVAL)`` so that ``rto_plot.py`` can read the
        analytics without re-running the simulation.
    """
    payload = (
        b"Adaptive-timeout SACK demo payload. "
        b"This block will be reconstructed byte-for-byte at the receiver. "
        + b"0" * 200
    ) * 9

    sim = NetworkSim(
        seed=9,
        logging=False,
        track_analytics=True,
        snapshot_interval=SNAPSHOT_INTERVAL,
    )
    network = Network(sim)

    # Node 1 is the sender; node 2 is the receiver.
    server = ATServer(
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
    client = ATClient(
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
        propagation_delay=_DELAY_BASE_MS,
        delay_variance=0,
        error_rate=0,
        max_queue_length=100,
        propagation_delay_fn=propagation_delay_fn,
    )
    network.add_channel(channel)
    channel.add_node(server)
    channel.add_node(client)

    sim.start()

    reconstructed = bytes(client.received_data)
    final_rto = server.retransmit_timeout
    final_srtt = int(server.smoothed_round_trip_time)
    final_svar = int(server.smoothed_variance)

    print(f"\nDelivered bytes         : {len(reconstructed)}")
    print(f"Expected bytes          : {len(payload)}")
    print(f"Server complete         : {server.is_complete()}")
    print(f"Payload matches         : {reconstructed == payload}")
    print(f"Sim time elapsed        : {sim.time} ms")
    print(f"Final RTO               : {final_rto} ms")
    print(f"Final SRTT              : {final_srtt} ms")
    print(f"Final SVAR              : {final_svar} ms")
    print(f"Analytics snapshots     : {len(sim.node_analytics)}")
    print(f"\n(Run rto_plot.py to visualise the RTO/SRTT/SVAR traces.)")

    return sim, SNAPSHOT_INTERVAL


if __name__ == "__main__":
    main()
