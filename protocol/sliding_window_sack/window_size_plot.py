"""
This file is meant to motivate the next step up from sliding window with 
selective ack. in particular, it shows that larger window sizes do not 
necessarily improve performance, and congestion control is needed in 
some form to over come this. the plot demonstrates that there is a sweet spot
of window sizes that minimize completion time, where exactly enough packets 
and acks are on the wire at the same time.

frames are 31 bytes for packets, and 24 bytes for acks, 
so for one seq we need 55 bytes on the wire

delay = 3 ms
bit rate = 30KBps = 240B/ms
so Bandwidth-delay product is 3ms * 240B/ms = 720 bytes

720/55 = 13.09, so the optimal window size is around 13/2 = 6.5 packets
which can be seen in the plot.
"""


from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys

import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.channel import Channel
from src.network import Network
from src.network_sim import NetworkSim

from protocol.sliding_window_sack.swsack_client import SWSACKClient
from protocol.sliding_window_sack.swsack_server import SWSACKServer


_HEADER = b"Sliding-window SACK demo payload. "
_CHUNK = b"This should be reconstructed exactly at the client." + b"0" * (52 * 5)
PAYLOAD = _HEADER + _CHUNK * 4

SEQ_SPACE = 1001
FRAME_SIZE = 2
RETRANSMIT_TIMEOUT = 20
BIT_RATE = 1000 * 8 * 30
PROPAGATION_DELAY = 3
DELAY_VARIANCE = 2
ERROR_RATE = 0
WINDOW_SIZES = list(range(1, 60, 1))
PLOT_OUTPUT = Path(__file__).with_name("window_size_completion_time.png")


def run_trial(window_size: int, seed: int = 8) -> tuple[int, bool]:
    sim = NetworkSim(seed=seed, logging=False)
    network = Network(sim)

    server = SWSACKServer(
        name=1,
        receiver=2,
        data=PAYLOAD,
        window_size=window_size,
        frame_size=FRAME_SIZE,
        retransmit_timeout=RETRANSMIT_TIMEOUT,
        seq_space=SEQ_SPACE,
    )
    client = SWSACKClient(
        name=2,
        server=1,
        buffer_window_size=window_size,
        seq_space=SEQ_SPACE,
        max_sack_blocks=4,
    )

    network.add_node(server)
    network.add_node(client)

    channel = Channel(
        bit_rate=BIT_RATE,
        propagation_delay=PROPAGATION_DELAY,
        delay_variance=DELAY_VARIANCE,
        error_rate=ERROR_RATE,
        max_queue_length=10
    )
    network.add_channel(channel)
    channel.add_node(server)
    channel.add_node(client)

    # Silence protocol debug prints while running a multi-point experiment.
    with redirect_stdout(StringIO()):
        sim.start()

    completed = server.is_complete() and bytes(client.received_data) == PAYLOAD
    return sim.time, completed


def collect_completion_times(window_sizes: list[int]) -> tuple[list[int], list[int]]:
    completion_times: list[int] = []
    completed_sizes: list[int] = []

    for window_size in window_sizes:
        if window_size >= SEQ_SPACE // 2:
            continue

        completion_time_ms, completed = run_trial(window_size)
        if not completed:
            continue

        completed_sizes.append(window_size)
        completion_times.append(completion_time_ms)

    return completed_sizes, completion_times

def calculate_optimal_window_size() -> float:
    frame_size = 31
    ack_size = 24
    bytes_per_seq = frame_size + ack_size

    bandwidth_delay_product_bytes = PROPAGATION_DELAY * (BIT_RATE / 1000)
    optimal_window_size = bandwidth_delay_product_bytes / bytes_per_seq
    return optimal_window_size/2

def plot_completion_times(window_sizes: list[int], completion_times: list[int]) -> None:
    optimal_window_size = calculate_optimal_window_size()

    
    plt.figure(figsize=(12, 7))
    plt.plot(window_sizes, completion_times, marker="o", linewidth=2, color="#1f77b4")
    plt.title(f"SWSACK Completion Time vs Window Size ({BIT_RATE // 8000} kbps, {PROPAGATION_DELAY} ms delay)")
    plt.xlabel("Window size (packets)")
    plt.ylabel("Completion time (ms)")
    plt.axvline(optimal_window_size, color="red", linestyle="--", label=f"Optimal window size ≈ {optimal_window_size:.2f}")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(PLOT_OUTPUT, dpi=150)
    plt.show()


def main() -> None:
    window_sizes, completion_times = collect_completion_times(WINDOW_SIZES)
    if not window_sizes:
        raise RuntimeError("No successful runs completed; nothing to plot.")

    for window_size, completion_time in zip(window_sizes, completion_times):
        print(f"window_size={window_size}, completion_time_ms={completion_time}")

    print(f"saved_plot={PLOT_OUTPUT}")

    plot_completion_times(window_sizes, completion_times)


if __name__ == "__main__":
    main()