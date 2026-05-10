# NetSim

NetSim is a discrete-event network simulator built to stress-test protocol behavior on unreliable links.
It provides a compact, extensible framework for modeling packet transport under queue pressure, delay,
jitter, and byte-level corruption.

## Features

- **Heap-based event engine** with seeded RNG for deterministic, reproducible runs
- **Rich channel model**: transmission time, propagation delay, jitter, queue overflow, byte-error injection
- **Unicast and broadcast** delivery (`BROADCAST_ID = 0xFFFFFFFF` delivers to all nodes on the channel)
- **CRC-32 packet integrity** with typed payloads (`bytes` or UTF-8 `str`)
- **Snapshot-based analytics** for throughput and drop counters
- **Three complete protocol implementations** with matching test suites

## Protocols

| Protocol | File | Description |
|---|---|---|
| Sliding Window + SACK | `protocol/sliding_window_sack/` | Fixed-RTO sliding window with selective retransmit |
| Adaptive Timeout | `protocol/adaptive_timeout/` | Jacobson/Karels SRTT/SVAR adaptive RTO + fast retransmit |
| TCP-like Congestion Control | `protocol/congestion_control/` | AIMD slow-start + fast retransmit/recovery + adaptive RTO |

## Architecture

```
src/
  network_sim.py  — discrete-event engine (heap queue, clock, seeded RNG, analytics)
  network.py      — topology container; schedules events on behalf of nodes
  node.py         — abstract base class: init / start / receive / snapshot
  channel.py      — queueing, transmission delay, propagation delay, error injection
  packet.py       — Packet dataclass; encode / decode / CRC-32 validate
  index.py        — public import surface

protocol/
  sliding_window_sack/   — SWSACKServer + SWSACKClient
  adaptive_timeout/      — ATServer + ATClient
  congestion_control/    — TCPServer + TCPClient

examples/
  bottleneck.py          — 30-node queue-saturation experiment
  bottleneck_plot.py     — histogram of throughput vs drops

tests/
  netsim/                — core simulator unit tests
  sliding_window_sack/   — SW+SACK protocol tests
  adaptive_timeout/      — adaptive RTO tests
  congestion_control/    — TCP-like congestion control tests
```

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -U pip
python -m pip install matplotlib numpy pytest

# Minimal two-node demo
python main.py

# Run all tests
python -m pytest -q
```

## Basic Usage

```python
from src.index import NetworkSim, Network, Channel, Node, Packet


class MyNode(Node):
    def init(self) -> None:
        pass

    def start(self) -> None:
        self.channels[0].send(Packet("hello", self.name, 2))

    def receive(self, packet: Packet) -> None:
        print(self.name, packet.src, packet.data)


sim = NetworkSim(seed=42, logging=False)
net = Network(sim)

n1 = MyNode(1)
n2 = MyNode(2)
net.add_node(n1)
net.add_node(n2)

ch = Channel(bit_rate=8_000, propagation_delay=10, error_rate=0)
net.add_channel(ch)
ch.add_node(n1)
ch.add_node(n2)

sim.start()
```

## Running Demos

```powershell
# Sliding-window SACK
python protocol/sliding_window_sack/example_entry.py

# Adaptive timeout (sinusoidal delay)
python protocol/adaptive_timeout/example_entry.py

# TCP-like congestion control
python protocol/congestion_control/example_entry.py

# Bottleneck experiment with plot
python examples/bottleneck_plot.py
```

## Analytics

Enable with `NetworkSim(track_analytics=True, snapshot_interval=N)`:

- Override `Node.snapshot()` to return per-node metrics each interval.
- `Channel.snapshot()` returns `[throughput, drops]` since the last snapshot.
- `sim.node_analytics` — per-interval element-wise sum of all node snapshots.
- `sim.channel_analytics` — per-interval element-wise sum of all channel snapshots.

## Deterministic Simulation

All randomness (jitter, error injection, tie-breaking) flows through a single
`random.Random` instance seeded at construction time.  The same seed always
produces the same sequence of events, making experiments reproducible and
diffs meaningful.

## Limitations / Non-goals

- Single-threaded; not intended for high-throughput performance benchmarks.
- No IP routing or multi-hop forwarding — all nodes share a single broadcast channel.
- Sequence numbers are modular integers, not byte-stream offsets.
- No connection setup/teardown (SYN/FIN); simulations run until the event queue drains.

## Notes

- `NetworkSim` prints run statistics after completion (simulation time, events processed, wall time, events/second).
