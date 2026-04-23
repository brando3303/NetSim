# NetSim

NetSim is a discrete-event network simulator built to stress-test protocol behavior on unreliable links.
It provides a compact, extensible framework for modeling packet transport under queue pressure, delay, and corruption.


- Performance-oriented core with a heap-based event engine and focused profiling workflow
- Clear systems design: modular simulation engine, network model, channel model, and packet layer
- Reliability-focused packet handling with checksum validation and typed payload support
- Built-in observability through snapshot-based throughput and drop analytics
- Practical experiments included for bottleneck analysis and visualization
- Solid verification baseline with 23 automated tests

## Technical Highlights

- Event-driven simulator with seeded RNG for reproducible runs
- Channel-level modeling of:
	- transmission time (bitrate-aware)
	- propagation delay and optional variance
	- queue overflow behavior
	- byte-level error injection
- Delivery semantics:
	- unicast to destination node
	- broadcast using `BROADCAST_ID = 0xFFFFFFFF`
- Packet wire format:
	- `src | dst | checksum | typed payload`

## Architecture

- `src/network_sim.py`: event scheduling, run loop, analytics orchestration
- `src/network.py`: network composition and simulation helper API
- `src/node.py`: abstract node contract (`init`, `start`, `receive`, optional `snapshot`)
- `src/channel.py`: queueing, transport behavior, delivery, and per-window channel counters
- `src/packet.py`: packet dataclass plus encode/decode/validate helpers
- `src/index.py`: single import surface for core public types

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -U pip
python -m pip install matplotlib numpy pytest

python .\main.py
python -m pytest tests/test_suite.py -q
```

## Example Usage

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

## Analytics and Experiments

Enable analytics with `NetworkSim(track_analytics=True, snapshot_interval=...)`.

- `Node.snapshot()` can be overridden for node-level metrics
- `Channel.snapshot()` returns `[throughput_since_last_snapshot, drops_since_last_snapshot]`
- `sim.node_analytics` stores per-snapshot, element-wise node metric aggregates
- `sim.channel_analytics` stores per-snapshot, element-wise channel metric aggregates

Included examples:

- `examples/bottleneck.py`: queue-length sensitivity experiment across 30 nodes
- `examples/bottleneck_plot.py`: time-window visualization of throughput vs drops

## Notes

- `NetworkSim` prints run statistics after completion (simulation time, events processed, wall time, events/second).
