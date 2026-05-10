"""Discrete-event simulation engine for NetSim.

The :class:`NetworkSim` class owns the global simulation time, the priority-queue
event heap, and the seeded random-number generator.  All timing throughout the
simulator is in *integer milliseconds*. 
(Although there is no reason it could not be pretended to be ns or other units)

Typical usage::

    sim = NetworkSim(seed=42)
    net = Network(sim)
    # … attach nodes and channels …
    sim.start()
"""
from __future__ import annotations

import heapq
import random
import itertools
import time

from typing import TYPE_CHECKING, Callable, Any, List

if TYPE_CHECKING:
  from .network import Network

class NetworkSim:
  """Discrete-event simulator.

  Owns the global simulation clock, the event heap, and the seeded RNG.
  All protocol and channel logic interacts with the simulation exclusively
  through :meth:`schedule_at` / :meth:`schedule_after` and the random helpers.

  Attributes:
      seed:              RNG seed used for this run (enables deterministic replay).
      rng:               Seeded :class:`random.Random` instance.
      eventQueue:        Min-heap of ``(time, tie_breaker, callback, args, kwargs)``.
                         ``tie_breaker`` is a random integer drawn from the seeded RNG
                         so that events scheduled at the same simulated time are
                         resolved in a repeatable but non-deterministic order.
      time:              Current simulation clock in milliseconds.
      running:           Set to ``False`` by :meth:`stop` to end the loop early.
      network:           The single :class:`~src.network.Network` attached to this sim.
      track_analytics:   When ``True``, periodic snapshots are collected into
                         ``node_analytics`` and ``channel_analytics``.
      snapshot_interval: How often (ms) analytics snapshots are taken.
  """

  def __init__(self, seed: int = 0, logging: bool = False, track_analytics: bool = False, snapshot_interval: int = 100):
    """Create a new simulation instance.

    Args:
        seed:              RNG seed.  Use the same seed to get identical event
                           orderings across runs (deterministic replay).
        logging:           When ``True``, every dequeued event is printed to
                           stdout.  Useful for debugging small scenarios.
        track_analytics:   When ``True``, node and channel snapshots are
                           collected every ``snapshot_interval`` ms.
        snapshot_interval: Interval in ms between analytics snapshots.
    """
    self.seed = seed
    self.rng = random.Random(seed)
    # Min-heap entries: (sim_time_ms, tie_breaker, callback, args, kwargs).
    # tie_breaker is a random integer drawn from the seeded RNG so that
    # same-time events are ordered reproducibly but without systematic bias
    # (e.g. always favouring the first-scheduled event).
    self.eventQueue: list = []
    heapq.heapify(self.eventQueue)
    self.time: int = 0
    self.logging = logging
    self.running = False
    self.network: Network | None = None
    self._event_ties = itertools.count()

    # Analytics
    self.track_analytics = track_analytics
    self.snapshot_interval = snapshot_interval
    self.node_analytics: list[list[int]] = []
    self.channel_analytics: list[list[int]] = []

  def add_network(self, network: Network) -> None:
    """Attach a :class:`~src.network.Network` to this simulation.

    Called automatically by :class:`~src.network.Network.__init__`; user code
    does not normally need to call this directly.
    """
    self.network = network


  def start(self) -> None:
    """Initialize the network, start all nodes, and run the event loop.

    Blocks until the event queue is empty or :meth:`stop` is called.
    """
    if self.network is None:
      raise RuntimeError("No network attached to the simulation.")
    self.network.init()
    self.running = True
    self.network.start()
    if self.track_analytics:
      self.schedule_after(self.snapshot_interval, self._collect_snapshot)
    self.simulation_loop()

  def simulation_loop(self) -> None:
    """Drain the event queue, advancing the simulation clock each step.

    Events are popped in (sim_time, random_tie_breaker) order.  The random
    tie-breaker makes the interleaving of same-time events repeatable under a
    fixed seed while avoiding systematic ordering bias.
    """
    wall_start = time.perf_counter()
    processed_events = 0

    while self.running:
      if len(self.eventQueue) == 0:
        break
      event_time, _tie, callback, args, kwargs = heapq.heappop(self.eventQueue)
      processed_events += 1
      self.time = event_time
      if self.logging:
        print(f"Time: {self.time}, Event: {callback.__name__}, Args: {args}, Kwargs: {kwargs}")
        print(f"Event Queue: {[ (time, queued_callback.__name__) for time, _queued_tie, queued_callback, _args, _kwargs in self.eventQueue ]}")
      callback(*args, **kwargs)

    wall_elapsed = time.perf_counter() - wall_start
    event_rate = processed_events / wall_elapsed if wall_elapsed > 0 else 0.0
    print(
      f"Simulation stats: sim_time_ms={self.time}, events_processed={processed_events}, "
      f"wall_time_s={wall_elapsed:.3f}, events_per_second={event_rate:.1f}"
    )

  def stop(self) -> None:
    """Signal the event loop to exit after the current event completes."""
    self.running = False


  # ------------------------------------------------------------------ #
  # Scheduling                                                           #
  # ------------------------------------------------------------------ #

  def schedule_at(self, time: int, callback: Callable, *args: Any, **kwargs: Any) -> None:
    """Schedule *callback* to fire at absolute simulation time *time* (ms).

    Raises :class:`ValueError` if *time* is in the past.
    A random tie-breaker drawn from the seeded RNG is stored alongside the
    event so that simultaneous events are ordered reproducibly.
    """
    if time < self.time:
      raise ValueError("Cannot schedule events in the past.")
    # The tie-breaker is a fresh random draw so two callers scheduling at the
    # same time don't collide on a monotonic counter (which would impose a
    # first-scheduled-wins ordering bias).
    event = (time, self.randint(0, 2**31 - 1), callback, args, kwargs)
    heapq.heappush(self.eventQueue, event)

  def schedule_after(self, delay: int, callback: Callable, *args: Any, **kwargs: Any) -> None:
    """Schedule *callback* to fire *delay* ms from now.

    Raises :class:`ValueError` if *delay* is negative.
    """
    if delay < 0:
      raise ValueError("Delay must be non-negative.")
    self.schedule_at(self.time + delay, callback, *args, **kwargs)


  # ------------------------------------------------------------------ #
  # Randomness                                                           #
  # ------------------------------------------------------------------ #

  def random(self) -> float:
    """Return the next float in [0.0, 1.0) from the seeded RNG."""
    return self.rng.random()
  
  def randint(self, a: int, b: int) -> int:
    """Return a random integer N such that a <= N <= b."""
    return self.rng.randint(a, b)

  def gauss(self, mu: float, sigma: float) -> float:
    """Return a Gaussian-distributed sample with mean *mu* and std *sigma*."""
    return self.rng.gauss(mu, sigma)
  

  # ------------------------------------------------------------------ #
  # Analytics                                                            #
  # ------------------------------------------------------------------ #

  def _collect_snapshot(self) -> None:
    """Collect one analytics snapshot from every node and channel.

    Reschedules itself every ``snapshot_interval`` ms while the event queue
    is non-empty, so snapshots stop automatically when the simulation ends.
    Each node's ``snapshot()`` method is expected to return a fixed-width list
    of integer metrics (or an empty list if the node doesn't track analytics).
    All per-node lists are summed element-wise before storage.
    """
    if self.network is None:
      return
    node_data = []
    channel_data = []
    for node in self.network.nodes:
      snap = getattr(node, 'snapshot', None)
      node_data.append(snap() if callable(snap) else [])
    for channel in self.network.channels:
      channel_data.append(channel.snapshot())
    self._process_analytics(node_data, channel_data)
    if len(self.eventQueue) > 0:
      self.schedule_after(self.snapshot_interval, self._collect_snapshot)

  def _process_analytics(self, node_data: List[List[int]], channel_data: List[List[int]]) -> None:
    """Sum per-node and per-channel snapshots and append to the analytics lists.

    Override this method in a subclass to implement custom aggregation logic.
    The default implementation sums all rows element-wise via
    :meth:`sum_analytics_matrix`.
    """
    summed_node_data = self.sum_analytics_matrix(node_data)
    summed_channel_data = self.sum_analytics_matrix(channel_data)
    self.node_analytics.append(summed_node_data)
    self.channel_analytics.append(summed_channel_data)

  def sum_analytics_matrix(self, matrix: List[List[int]]) -> List[int]:
    """Return the element-wise sum of all rows in *matrix*.

    All rows must have the same length.  Returns an empty list if *matrix*
    is empty. This is mostly just a helper and optional depending on the type of analytics being collected.
    It's the default but can be overridden for more complex processing.

    Raises:
        ValueError: If rows have inconsistent lengths.
    """
    if len(matrix) == 0:
      return []
    width = len(matrix[0])
    summed = [0] * width
    for row in matrix:
      if len(row) != width:
        raise ValueError("All rows must have the same length")
      for index, value in enumerate(row):
        summed[index] += value
    return summed
