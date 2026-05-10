"""NetSim quick-start: a minimal two-node simulation.

This script demonstrates the core NetSim workflow in the fewest possible steps:

1. Create a :class:`~src.network_sim.NetworkSim` (discrete-event engine).
2. Wrap it in a :class:`~src.network.Network` (topology container / scheduling
   proxy).
3. Implement a :class:`~src.node.Node` subclass with ``start`` and ``receive``
   logic.
4. Wire two nodes together through a :class:`~src.channel.Channel`.
5. Call ``sim.start()`` to run the simulation to completion.

For more complex examples see the ``protocol/`` directory.
"""
from __future__ import annotations

from src.index import Channel, Network, NetworkSim, Node, Packet


class SenderNode(Node):
    """Sends one greeting to node 2 at simulation start."""

    def init(self) -> None:
        pass

    def start(self) -> None:
        """Send a single packet to node 2 at simulation time 0."""
        self.channels[0].send(Packet("Hello from node 1!", src=self.name, dst=2))

    def receive(self, packet: Packet) -> None:
        print(f"[t={self.network.sim.time} ms] node {self.name} received: {packet.data!r}")


class ReceiverNode(Node):
    """Receives packets and prints them."""

    def init(self) -> None:
        pass

    def start(self) -> None:
        pass  # Receiver is passive; it waits for incoming packets.

    def receive(self, packet: Packet) -> None:
        print(f"[t={self.network.sim.time} ms] node {self.name} received: {packet.data!r}")


def main() -> None:
    # --- 1. Simulation engine (seeded for reproducibility) ---
    sim = NetworkSim(seed=42, logging=False)

    # --- 2. Network topology container ---
    network = Network(sim)

    # --- 3. Create two nodes ---
    node1 = SenderNode(name=1)
    node2 = ReceiverNode(name=2)
    network.add_node(node1)
    network.add_node(node2)

    # --- 4. Create a channel and attach both nodes to it ---
    #   bit_rate          = 8 000 bps  (8 bits/byte -> 1 byte/ms effective rate)
    #   propagation_delay = 10 ms one-way latency
    channel = Channel(bit_rate=8_000, propagation_delay=10)
    network.add_channel(channel)
    channel.add_node(node1)
    channel.add_node(node2)

    # --- 5. Run the simulation ---
    sim.start()

    print("Simulation complete.")


if __name__ == "__main__":
    main()
