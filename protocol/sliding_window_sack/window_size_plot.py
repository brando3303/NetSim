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


PAYLOAD = (
    b"Sliding-window SACK demo payload. "
    b"This should be reconstructed exactly at the client."
    b"0000000000000000000000000000000000000000000000000000"
    b"0000000000000000000000000000000000000000000000000000"
    b"0000000000000000000000000000000000000000000000000000"
    b"0000000000000000000000000000000000000000000000000000"
    b"0000000000000000000000000000000000000000000000000000"
)

SEQ_SPACE = 1001
FRAME_SIZE = 2
RETRANSMIT_TIMEOUT = 20
BIT_RATE = 1000 * 8 * 10
PROPAGATION_DELAY = 3
DELAY_VARIANCE = 200
ERROR_RATE = 5
WINDOW_SIZES = list(range(5, 50, 1))
PLOT_OUTPUT = Path(__file__).with_name("window_size_completion_time.png")


def run_trial(window_size: int, seed: int = 7) -> tuple[int, bool]:
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
        max_queue_length=25
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


def plot_completion_times(window_sizes: list[int], completion_times: list[int]) -> None:
    plt.figure(figsize=(12, 7))
    plt.plot(window_sizes, completion_times, marker="o", linewidth=2, color="#1f77b4")
    plt.title("SWSACK Completion Time vs Window Size")
    plt.xlabel("Window size (packets)")
    plt.ylabel("Completion time (ms)")
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