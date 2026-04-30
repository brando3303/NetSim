from __future__ import annotations

import heapq
import random
import itertools
import time

from typing import TYPE_CHECKING, Callable, Any, List

if TYPE_CHECKING:
  from .network import Network

class NetworkSim:

  def __init__(self, seed=0, logging=False, track_analytics=False, snapshot_interval=100):
    self.seed = seed
    self.rng = random.Random(seed)
    self.eventQueue = []
    heapq.heapify(self.eventQueue)
    self.time = 0
    self.logging = logging
    self.running = False
    self.network: Network | None = None
    self._event_ties = itertools.count()

    # Analytics
    self.track_analytics = track_analytics
    self.snapshot_interval = snapshot_interval
    self.node_analytics = []
    self.channel_analytics = []

  def add_network(self, network: Network):
    self.network = network


  def start(self):
    if self.network is None:
      raise Exception("No network added to the simulation.")
    self.network.init()
    self.running = True
    self.network.start()
    if self.track_analytics:
      self.schedule_after(self.snapshot_interval, self._collect_snapshot)
    self.simulation_loop()

  def simulation_loop(self):
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

  def stop(self):
    self.running = False


  # Helpers

  # Scheduling

  def schedule_at(self, time: int, callback: Callable, *args, **kwargs):
    if time < self.time:
      raise ValueError("Cannot schedule events in the past.")
    event = (time, self.randint(0, 2**31 - 1), callback, args, kwargs)
    heapq.heappush(self.eventQueue, event)

  def schedule_after(self, delay: int, callback: Callable, *args, **kwargs):
    if delay < 0:
      raise ValueError("Delay must be non-negative.")
    self.schedule_at(self.time + delay, callback, *args, **kwargs)


  # Randomness

  def random(self):
    return self.rng.random()
  
  def randint(self, a: int, b: int):
    return self.rng.randint(a, b)

  def gauss(self, mu: float, sigma: float):
    return self.rng.gauss(mu, sigma)
  

  # Analytics
  def _collect_snapshot(self):
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

  
  def _process_analytics(self, node_data: List, channel_data: List):
    """
    Default analytics processing sums node metrics element-wise.
    It can be overridden to implement custom analytics processing.
    """
    summed_node_data = self.sum_analytics_matrix(node_data)
    summed_channel_data = self.sum_analytics_matrix(channel_data)

    self.node_analytics.append(summed_node_data)
    self.channel_analytics.append(summed_channel_data)

  def sum_analytics_matrix(self, matrix: List[List[int]]) -> List[int]:
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
