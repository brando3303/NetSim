from __future__ import annotations

from pathlib import Path
import numpy as np
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.channel import Channel
from src.network import Network
from src.network_sim import NetworkSim

from protocol.adaptive_timeout.at_client import ATClient
from protocol.adaptive_timeout.at_server import ATServer


def main():
    payload = (
        b"Adaptive-timeout SACK demo payload. "
        b"This should be reconstructed exactly at the client."
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
                b"Adaptive-timeout SACK demo payload. "
        b"This should be reconstructed exactly at the client."
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
                b"Adaptive-timeout SACK demo payload. "
        b"This should be reconstructed exactly at the client."
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
                b"Adaptive-timeout SACK demo payload. "
        b"This should be reconstructed exactly at the client."
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
                b"Adaptive-timeout SACK demo payload. "
        b"This should be reconstructed exactly at the client."
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
                b"Adaptive-timeout SACK demo payload. "
        b"This should be reconstructed exactly at the client."
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
                b"Adaptive-timeout SACK demo payload. "
        b"This should be reconstructed exactly at the client."
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
                b"Adaptive-timeout SACK demo payload. "
        b"This should be reconstructed exactly at the client."
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
                b"Adaptive-timeout SACK demo payload. "
        b"This should be reconstructed exactly at the client."
        b"0000000000000000000000000000000000000000000000000000"
        b"0000000000000000000000000000000000000000000000000000"
    )

    seq_space = 1001
    snapshot_interval = 10

    sim = NetworkSim(seed=9, logging=False, track_analytics=True, snapshot_interval=snapshot_interval)
    network = Network(sim)

    server = ATServer(
        name=1,
        receiver=2,
        data=payload,
        window_size=10,
        frame_size=4,
        retransmit_timeout=1000,
        seq_space=seq_space,
        min_rto=10,
        max_rto=500,
    )
    client = ATClient(
        name=2,
        server=1,
        buffer_window_size=10,
        seq_space=seq_space,
        max_sack_blocks=4,
    )

    network.add_node(server)
    network.add_node(client)

    channel = Channel(
        bit_rate=1000 * 8 * 100,
        propagation_delay=5,
        delay_variance=0,
        error_rate=0,
        max_queue_length=100,
        propagation_delay_fn=lambda x: np.sin(x*2*np.pi*(1/1000))*20+ 30,
    )
    network.add_channel(channel)
    channel.add_node(server)
    channel.add_node(client)

    sim.start()

    reconstructed = bytes(client.received_data)
    print(f"Delivered bytes: {len(reconstructed)}")
    print(f"Server complete: {server.is_complete()}")
    print(f"Payload matches: {reconstructed == payload}")
    print(f"Final adaptive RTO: {server.retransmit_timeout} ms")
    print(f"Analytics snapshots collected: {len(sim.node_analytics)}")
    if sim.node_analytics:
        print(f"First snapshot: {sim.node_analytics[0]}")
        print(f"Last snapshot: {sim.node_analytics[-1]}")
    
    return sim, snapshot_interval


if __name__ == "__main__":
    sim, _ = main()
