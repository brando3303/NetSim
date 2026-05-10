"""Network topology model for NetSim.

A :class:`Network` groups nodes and channels into a single topology and acts as
the scheduling proxy between protocol logic and the :class:`~src.network_sim.NetworkSim`
engine.  Protocol code (nodes, channels) calls :meth:`Network.schedule_after` rather
than reaching into the simulator directly, which keeps the API surface clean.

Typical usage::

    sim = NetworkSim(seed=42)
    net = Network(sim)          # registers itself with the simulator
    net.add_node(my_node)
    net.add_channel(my_channel)
    sim.start()
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
  from .network_sim import NetworkSim
  from .node import Node
  from .channel import Channel

class Network:
  """Container for nodes and channels that share a simulated medium.

  The network is the bridge between user-constructed topologies and the
  underlying :class:`~src.network_sim.NetworkSim` event engine.  It validates
  the topology at start-up (via :meth:`init`) and provides scheduling and RNG
  helpers so that nodes and channels don't need a direct reference to the
  simulator.

  Attributes:
      sim:         The parent :class:`~src.network_sim.NetworkSim` instance.
      nodes:       Ordered list of :class:`~src.node.Node` instances in this network.
      channels:    Ordered list of :class:`~src.channel.Channel` instances.
      initialized: ``True`` after :meth:`init` has run successfully.
  """

  def __init__(self, sim: NetworkSim):
    """Create a network and register it with *sim*.

    Calling this constructor automatically attaches the network to *sim* via
    :meth:`~src.network_sim.NetworkSim.add_network`.
    """
    self.sim = sim
    self.nodes: list[Node] = []
    self.channels: list[Channel] = []
    self.sim.add_network(self)
    self.initialized = False

  def init(self) -> None:
    """Validate the topology and call ``init()`` on every node.

    Raises:
        RuntimeError: If the network has no nodes.
    """
    if len(self.nodes) == 0:
      raise RuntimeError("Network must have at least one node.")
    if self.sim is None:
      raise RuntimeError("Network must be added to a simulation.")
    for node in self.nodes:
      node.init()
    self.initialized = True

  def start(self) -> None:
    """Call ``start()`` on every node, triggering initial packet transmissions.

    Raises:
        RuntimeError: If :meth:`init` has not been called first.
    """
    if not self.initialized:
      raise RuntimeError("Network must be initialized before starting.")
    for node in self.nodes:
      node.start()

  def add_node(self, node: Node) -> None:
    """Append *node* to this network and set ``node.network = self``."""
    self.nodes.append(node)
    node.network = self

  def add_channel(self, channel: Channel) -> None:
    """Append *channel* to this network and set ``channel.network = self``."""
    self.channels.append(channel)
    channel.network = self


  # ------------------------------------------------------------------ #
  # Scheduling / RNG proxy — delegates to the parent NetworkSim          #
  # ------------------------------------------------------------------ #

  def schedule_at(self, time: int, callback: Callable, *args, **kwargs) -> None:
    """Proxy for :meth:`~src.network_sim.NetworkSim.schedule_at`."""
    self.sim.schedule_at(time, callback, *args, **kwargs)

  def schedule_after(self, delay: int, callback: Callable, *args, **kwargs) -> None:
    """Proxy for :meth:`~src.network_sim.NetworkSim.schedule_after`."""
    self.sim.schedule_after(delay, callback, *args, **kwargs)

  def random(self) -> float:
    """Return the next float in [0.0, 1.0) from the simulation's seeded RNG."""
    return self.sim.rng.random()
  
  def randint(self, a: int, b: int) -> int:
    """Return a random integer N such that a <= N <= b."""
    return self.sim.rng.randint(a, b)
  
  def gauss(self, mu: float, sigma: float) -> float:
    """Return a Gaussian-distributed sample with mean *mu* and std *sigma*."""
    return self.sim.rng.gauss(mu, sigma)