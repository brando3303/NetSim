from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from src.channel import Channel
from src.network import Network
from src.network_sim import NetworkSim

from protocol.congestion_control.cc_client import TCPClient
from protocol.congestion_control.cc_server import TCPServer


def main():
	payload = (
		b"Congestion-control demo payload. "
		b"This should be reconstructed exactly at the client. "
		b"0000000000000000000000000000000000000000000000000000"
		b"0000000000000000000000000000000000000000000000000000"
	) * 10

	seq_space = 512
	window_size = 16
	snapshot_interval = 50

	sim = NetworkSim(
		seed=42,
		logging=False,
		track_analytics=False,
		snapshot_interval=snapshot_interval,
	)
	network = Network(sim)

	server = TCPServer(
		name=1,
		receiver=2,
		data=payload,
		window_size=window_size,
		frame_size=8,
		retransmit_timeout=500,
		seq_space=seq_space,
		min_rto=20,
		max_rto=10_000,
	)
	client = TCPClient(
		name=2,
		server=1,
		buffer_window_size=window_size,
		seq_space=seq_space,
		max_sack_blocks=4,
	)

	network.add_node(server)
	network.add_node(client)

	# Channel with moderate loss and variable delay to exercise congestion control
	channel = Channel(
		bit_rate=1000 * 8 * 100,
		propagation_delay=10,
		delay_variance=0,
		error_rate=0,
		max_queue_length=200,
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
	print(f"Final cwnd       : {server.congestion_window}")
	print(f"Final cThresh    : {server.congestion_threshold}")
	print(f"Final RTO        : {server.retransmit_timeout} ms")


if __name__ == "__main__":
	main()
