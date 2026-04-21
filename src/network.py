from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
  from .network_sim import NetworkSim
  from .node import Node
  from .channel import Channel

class Network:
  
  def __init__(self, sim: NetworkSim):
    self.sim = sim
    self.nodes: list[Node] = []
    self.channels: list[Channel] = []
    self.sim.add_network(self)
    self.initialized = False

  def init(self):
    if len(self.nodes) == 0:
      raise RuntimeError("Network must have at least one node.")
    if self.sim is None:
      raise RuntimeError("Network must be added to a simulation.")
    for node in self.nodes:
      node.init()
    self.initialized = True

  def start(self):
    if not self.initialized:
      raise RuntimeError("Network must be initialized before starting.")
    for node in self.nodes:
      node.start()

  def add_node(self, node: Node):
    self.nodes.append(node)
    node.network = self

  def add_channel(self, channel: Channel):
    self.channels.append(channel)
    channel.network = self


  # Helpers (API for nodes and channels to interact with the simulation)
  def schedule_at(self, time: int, callback: Callable, *args, **kwargs):
    self.sim.schedule_at(time, callback, *args, **kwargs)

  def schedule_after(self, delay: int, callback: Callable, *args, **kwargs):
    self.sim.schedule_after(delay, callback, *args, **kwargs)

  def random(self):
    return self.sim.rng.random()
  
  def randint(self, a: int, b: int):
    return self.sim.rng.randint(a, b)
  
  def gauss(self, mu: float, sigma: float):
    return self.sim.rng.gauss(mu, sigma)