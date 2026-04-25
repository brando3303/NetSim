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


def main():
    payload = (
        b"Sliding-window SACK demo payload. "
        b"This should be reconstructed exactly at the client."
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
    )

    seq_space = 1001

    sim = NetworkSim(seed=7, logging=False)
    network = Network(sim)

    server = SWSACKServer(
        name=1,
        receiver=2,
        data=payload,
        window_size=10,
        frame_size=40,
        retransmit_timeout=8,
        seq_space=seq_space,
    )
    client = SWSACKClient(
        name=2,
        server=1,
        buffer_window_size=10,
        seq_space=seq_space,
        max_sack_blocks=4,
    )

    network.add_node(server)
    network.add_node(client)

    channel = Channel(
        bit_rate=1000 * 8*100,
        propagation_delay=3,
        delay_variance=200,
        error_rate=50,
    )
    network.add_channel(channel)
    channel.add_node(server)
    channel.add_node(client)

    sim.start()

    reconstructed = bytes(client.received_data)
    print(f"Delivered bytes: {len(reconstructed)}")
    print(f"Server complete: {server.is_complete()}")
    print(f"Payload matches: {reconstructed == payload}")
    print(reconstructed.decode("utf-8"))


if __name__ == "__main__":
    main()
