from __future__ import annotations

import heapq
import random
import itertools

from dataclasses import dataclass
from collections import deque
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

  def add_network(self, network: Network):
    self.network = network


  def start(self):
    if self.network == None:
      raise Exception("No network added to the simulation.")
    self.network.init()
    self.running = True
    self.network.start()
    self.simulation_loop()

  def simulation_loop(self):
    while self.running:
      if len(self.eventQueue) == 0:
        break
      event = heapq.heappop(self.eventQueue)
      self.time = event.time
      if self.logging:
        print(f"Time: {self.time}, Event: {event.callback.__name__}, Args: {event.args}, Kwargs: {event.kwargs}")
        print(f"Event Queue: {[ (e.time, e.callback.__name__) for e in self.eventQueue ]}")
      event.callback(*event.args, **event.kwargs)

  def stop(self):
    self.running = False


  # Helpers

  # Scheduling

  def schedule_at(self, time: int, callback: Callable, *args, **kwargs):
    if time < self.time:
      raise Exception("Cannot schedule events in the past.")
    event = Event(time, self.rng.randint(0, 2**32 - 1), callback, args, kwargs)
    heapq.heappush(self.eventQueue, event)

  def schedule_after(self, delay: int, callback: Callable, *args, **kwargs):
    if delay < 0:
      raise Exception("Delay must be non-negative.")
    self.schedule_at(self.time + delay, callback, *args, **kwargs)


  # Randomness

  def random(self):
    return self.rng.random()
  
  def randint(self, a: int, b: int):
    return self.rng.randint(a, b)

  def gauss(self, mu: float, sigma: float):
    return self.rng.gauss(mu, sigma)
  
@dataclass(order=True)
class Event:
  time: int
  tie: int
  callback: Callable
  args: Any = None
  kwargs: Any = None