"""Sliding-window-with-SACK demo.

Demonstrates :class:`~protocol.sliding_window_sack.swsack_server.SWSACKServer`
transferring a multi-frame payload to
:class:`~protocol.sliding_window_sack.swsack_client.SWSACKClient` over a
lossless channel.  Run this file directly to confirm that the reconstructed
bytes match the original payload exactly.

Background
----------
A sliding window lets the sender keep up to ``WINDOW_SIZE`` frames in flight
without waiting for individual acknowledgements, keeping the link busy.
SACK (Selective Acknowledgment) lets the receiver report gaps in the received
sequence so the sender only retransmits missing frames rather than the entire
outstanding window.

The window-size / throughput trade-off is explored further in
``window_size_plot.py``: a window that is too small under-utilises the link,
while one that is too large can build up a queue and increase latency.  A
useful rule of thumb is to size the window around the *bandwidth-delay product*
(see the constant block below).

It is easy to see that manually tuning the sender and reciever can be difficult to get right,
which sets the stage for methods of automatically adapating ot the network contditions to achieve
good throughput without much setup, similar to modern transport protocols.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.channel import Channel
from src.network import Network
from src.network_sim import NetworkSim

from protocol.sliding_window_sack.swsack_client import SWSACKClient
from protocol.sliding_window_sack.swsack_server import SWSACKServer

# ---------------------------------------------------------------------------
# Tunable parameters
# ---------------------------------------------------------------------------

#: Size of the sequence-number space.  Must satisfy ``WINDOW_SIZE < SEQ_SPACE // 2``.
SEQ_SPACE = 1024

#: Maximum number of unacknowledged frames the sender may have in flight.
WINDOW_SIZE = 10

#: Maximum payload bytes carried by a single data frame.
FRAME_SIZE = 16

#: Initial retransmit timeout in milliseconds.
RETRANSMIT_TIMEOUT = 50

#: Channel transmission rate in bits per second.
BIT_RATE = 1_000 * 8 * 100  # 800 kbps

#: One-way propagation delay in milliseconds.
PROPAGATION_DELAY = 4  # ms

# Bandwidth-delay product (BDP) estimate – useful for choosing WINDOW_SIZE:
#
#   RTT  ≈ 2 × PROPAGATION_DELAY = 8 ms = 0.008 s
#   BDP  = BIT_RATE × RTT / 8 = 800_000 × 0.008 / 8 = 800 bytes
#
# At FRAME_SIZE = 16 B this is ~50 frames per RTT.  WINDOW_SIZE = 10 keeps
# ~20 % of the pipe filled, which is intentionally conservative so the
# example completes quickly.  Raise WINDOW_SIZE toward 50 to approach full
# link utilisation (see window_size_plot.py for a sweep).


def main() -> NetworkSim:
    """Run the sliding-window SACK demo and print a results summary."""
    payload = (
        b"Sliding-window SACK demo payload. "
        b"This block will be reconstructed byte-for-byte at the receiver. "
        + b"0" * 200
    ) * 3

    sim = NetworkSim(seed=7, logging=False)
    network = Network(sim)

    # Node 1 is the sender; node 2 is the receiver.
    server = SWSACKServer(
        name=1,
        receiver=2,
        data=payload,
        window_size=WINDOW_SIZE,
        frame_size=FRAME_SIZE,
        retransmit_timeout=RETRANSMIT_TIMEOUT,
        seq_space=SEQ_SPACE,
    )
    client = SWSACKClient(
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
        propagation_delay=PROPAGATION_DELAY,
        delay_variance=0,
        error_rate=0,
    )
    network.add_channel(channel)
    channel.add_node(server)
    channel.add_node(client)

    sim.start()

    reconstructed = bytes(client.received_data)
    print(f"\nDelivered bytes  : {len(reconstructed)}")
    print(f"Expected bytes   : {len(payload)}")
    print(f"Server complete  : {server.is_complete()}")
    print(f"Payload matches  : {reconstructed == payload}")
    print(f"Sim time elapsed : {sim.time} ms")

    return sim


if __name__ == "__main__":
    main()
