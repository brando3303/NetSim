# NetSim

NetSim is a discrete-event network simulator for testing protocols over unreliable links.
It models nodes connected by channels with configurable bitrate, propagation delay, queue limits,
and error injection.

## Current State

- Core simulation engine with event scheduling and reproducible RNG seed support
- Packet wire format with checksum validation (`src`, `dst`, `checksum`, typed payload)
- Channel queueing, transmission timing, propagation delay, and byte-level error injection
- Unicast + broadcast delivery (`BROADCAST_ID = 0xFFFFFFFF`)
- Analytics snapshots for nodes/channels via `snapshot()`
- Example workloads for bottleneck analysis and plotting
- Test suite currently contains 23 tests

## Project Layout

- `src/network_sim.py`: event queue, run loop, scheduling helpers, analytics collection
- `src/network.py`: network container and helper API exposed to nodes/channels
- `src/node.py`: abstract node base class (`init`, `start`, `receive`, optional `snapshot`)
- `src/channel.py`: channel behavior (queue, delay, errors, delivery, channel snapshot stats)
- `src/packet.py`: packet model and encode/decode/validate utilities
- `src/index.py`: convenient public imports for core types
- `examples/bottleneck.py`: queue-length experiment with stop-and-wait traffic
- `examples/bottleneck_plot.py`: throughput/drop analytics plotting example
- `tests/test_suite.py`: unit/integration-style behavior checks

## Quick Start

### 1) Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2) Install dependencies

```powershell
python -m pip install -U pip
python -m pip install matplotlib numpy pytest
```

### 3) Run the demo simulation

```powershell
python .\main.py
```

### 4) Run the test suite

```powershell
python -m pytest tests/test_suite.py -q
```

## Basic Usage

```python
from src.index import NetworkSim, Network, Channel, Node, Packet


class MyNode(Node):
	def init(self):
		pass

	def start(self):
		self.channels[0].send(Packet("hello", self.name, 2))

	def receive(self, packet: Packet):
		print(self.name, packet.src, packet.data)


sim = NetworkSim(seed=42, logging=False)
net = Network(sim)

n1 = MyNode(1)
n2 = MyNode(2)
net.add_node(n1)
net.add_node(n2)

ch = Channel(bit_rate=1000 * 8, propogation_delay=0, error_rate=0)
net.add_channel(ch)
ch.add_node(n1)
ch.add_node(n2)

sim.start()
```

## Analytics

If `NetworkSim(track_analytics=True, snapshot_interval=...)` is enabled, snapshots are
collected periodically while the simulation runs.

- `Node.snapshot()` defaults to `[]`; override in custom node classes for metrics
- `Channel.snapshot()` returns `[throughput_since_last_snapshot, drops_since_last_snapshot]`
- `sim.node_analytics` stores per-snapshot element-wise sums of node snapshots
- `sim.channel_analytics` stores per-snapshot element-wise sums of channel snapshots

Example:

```python
sim = NetworkSim(seed=13, logging=False, track_analytics=True, snapshot_interval=100)
# ... build and run network ...

throughput_series = [snap[0] for snap in sim.channel_analytics]
drop_series = [snap[1] for snap in sim.channel_analytics]
```

## Notes

- `NetworkSim` prints final run stats (sim time, events processed, wall time, events/sec).
- Event tie ordering for identical timestamps is currently randomized.
