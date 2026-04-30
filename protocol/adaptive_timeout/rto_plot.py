from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from protocol.adaptive_timeout.example_entry import main


def _build_histogram_x(bucket_count: int, window_ms: int) -> list[int]:
    return [i * window_ms for i in range(bucket_count)]


def _pad_histograms(*series: list[int]) -> list[list[int]]:
    max_len = max((len(s) for s in series), default=0)
    padded: list[list[int]] = []
    for s in series:
        padded.append(s + [0] * (max_len - len(s)))
    return padded


def run_adaptive_timeout_experiment() -> tuple[list[int], list[int], list[int], int]:
    """Run the adaptive timeout simulation and collect RTO analytics.
    
    Returns:
        (rto_values, srrt_values, svar_values, window_ms)
    """
    sim, snapshot_interval = main()

    # sim.node_analytics is a list of aggregated snapshots.
    # Each element is the result of sum_analytics_matrix([client_snap, server_snap])
    # Since client returns [0, 0, 0] and server returns [rto, srrt, svar],
    # each snapshot is [rto_sum, srrt_sum, svar_sum]
    
    rto_values = []
    srrt_values = []
    svar_values = []
    
    for snapshot in sim.node_analytics:
        # snapshot is [rto, srrt, svar]
        if len(snapshot) >= 3:
            rto_values.append(snapshot[0])
            srrt_values.append(snapshot[1])
            svar_values.append(snapshot[2])
    
    return rto_values, srrt_values, svar_values, snapshot_interval


def plot_rto_adaptation(
    rto_values: list[int],
    srrt_values: list[int],
    svar_values: list[int],
    window_ms: int,
) -> None:
    """Plot RTO adaptation over time."""
    rto_values, srrt_values, svar_values = _pad_histograms(rto_values, srrt_values, svar_values)
    x = _build_histogram_x(len(rto_values), window_ms)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

    # Plot 1: Retransmit Timeout over time
    ax1.plot(x, rto_values, marker="o", linewidth=2, color="tab:red", label="RTO")
    ax1.set_title("Adaptive Retransmit Timeout Over Time")
    ax1.set_xlabel(f"Simulation time (ms), window={window_ms}ms")
    ax1.set_ylabel("RTO (ms)")
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    # Plot 2: Smoothed RTT and Variance
    ax2.plot(x, srrt_values, marker="s", linewidth=2, color="tab:blue", label="Smoothed RTT")
    ax2.plot(x, svar_values, marker="^", linewidth=2, color="tab:green", label="Smoothed Variance")
    ax2.set_title("RTT Estimation Components")
    ax2.set_xlabel(f"Simulation time (ms), window={window_ms}ms")
    ax2.set_ylabel("Value (ms)")
    ax2.grid(True, alpha=0.3)
    ax2.legend()

    plt.tight_layout()
    
    # Save to file instead of showing
    output_path = Path(__file__).with_name("rto_adaptation.png")
    plt.savefig(output_path, dpi=100, bbox_inches='tight')
    plt.show()
    print(f"Plot saved to: {output_path}")


if __name__ == "__main__":
    print("Running adaptive timeout simulation with analytics collection...")
    rto, srrt, svar, window = run_adaptive_timeout_experiment()
    print(f"Collected {len(rto)} snapshots over {window}ms intervals")
    print(f"RTO range: {min(rto) if rto else 0} - {max(rto) if rto else 0} ms")
    print(f"SRRT range: {min(srrt) if srrt else 0} - {max(srrt) if srrt else 0} ms")
    plot_rto_adaptation(rto, srrt, svar, window)
