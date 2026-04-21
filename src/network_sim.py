from __future__ import annotations

import heapq
import random
import itertools
import time

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Any

if TYPE_CHECKING:
  from .network import Network

class NetworkSim:

  def __init__(self, seed=0, logging=False):
    self.seed = seed
    self.rng = random.Random(seed)
    self.eventQueue = []
    heapq.heapify(self.eventQueue)
    self.time = 0
    self.logging = logging
    self.running = False
    self.network: Network | None = None
    self._event_ties = itertools.count()

  def add_network(self, network: Network):
    self.network = network


  def start(self):
    if self.network is None:
      raise Exception("No network added to the simulation.")
    self.network.init()
    self.running = True
    self.network.start()
    self.simulation_loop()

  def simulation_loop(self):
    # wall_start = time.perf_counter()
    # processed_events = 0

    while self.running:
      if len(self.eventQueue) == 0:
        break
      event = heapq.heappop(self.eventQueue)
      # processed_events += 1
      self.time = event.time
      if self.logging:
        print(f"Time: {self.time}, Event: {event.callback.__name__}, Args: {event.args}, Kwargs: {event.kwargs}")
        print(f"Event Queue: {[ (e.time, e.callback.__name__) for e in self.eventQueue ]}")
      event.callback(*event.args, **event.kwargs)

    # wall_elapsed = time.perf_counter() - wall_start
    # event_rate = processed_events / wall_elapsed if wall_elapsed > 0 else 0.0
    # print(
    #   f"Simulation stats: sim_time_ms={self.time}, events_processed={processed_events}, "
    #   f"wall_time_s={wall_elapsed:.3f}, events_per_second={event_rate:.1f}"
    # )

  def stop(self):
    self.running = False


  # Helpers

  # Scheduling

  def schedule_at(self, time: int, callback: Callable, *args, **kwargs):
    if time < self.time:
      raise ValueError("Cannot schedule events in the past.")
    event = Event(time, self.rng.randint(0, 1 << 30), callback, args, kwargs) # TODO make this random tie
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
  
@dataclass(order=True, slots=True)
class Event:
  time: int
  tie: int
  callback: Callable = field(compare=False)
  args: Any = field(default=None, compare=False)
  kwargs: Any = field(default=None, compare=False)