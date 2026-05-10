"""Abstract base class for all nodes in a NetSim topology.

A *node* represents any endpoint that can send and receive packets.  Protocol
implementations (clients, servers, routers) subclass :class:`Node` and override
:meth:`init`, :meth:`start`, and :meth:`receive`.

Nodes interact with the simulation through:

* ``self.channels``  — the list of :class:`~src.channel.Channel` instances the
  node is connected to (assigned by :meth:`~src.channel.Channel.add_node`).
* ``self.network``   — the parent :class:`~src.network.Network`, used to
  schedule timers via :meth:`set_timer`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, List

if TYPE_CHECKING:
  from .network import Network
  from .packet import Packet

class Node(ABC):
  """Abstract base for all protocol nodes.

  Subclasses must implement:

  * :meth:`init`    — called once before the simulation starts; set up state.
  * :meth:`start`   — called once when the simulation begins; send initial packets.
  * :meth:`receive` — called whenever a packet addressed to this node arrives.

  Optionally override:

  * :meth:`snapshot`        — return a fixed-width list of integer metrics for
                               analytics aggregation.
  * :meth:`validate_packet` — apply application-level filtering before
                               :meth:`receive` is called.
  """
  def __init__(self, name: int):
    """Create a node with the given integer identifier.

    Args:
        name: A unique integer identifier for this node.  Used as the source
              or destination address in packet headers.
    """
    self.name = name
    self.channels: list = []
    self._network: Network | None = None

  @property
  def network(self) -> Network:
    if self._network is None:
      raise RuntimeError("Node is not attached to a network")
    return self._network

  @network.setter
  def network(self, value: Network) -> None:
      if value is None:
          raise ValueError("network cannot be None")
      self._network = value

  @abstractmethod
  def init(self) -> None:
    """Initialize node state before the simulation starts.

    Called once by :meth:`~src.network.Network.init` before any events are
    scheduled.  Use this to set up mutable state that depends on knowing
    the network topology.
    """
    raise NotImplementedError

  @abstractmethod
  def start(self) -> None:
    """Begin protocol activity at simulation time 0.

    Called once by :meth:`~src.network.Network.start` immediately before the
    event loop begins.  Senders typically queue their first packets here.
    """
    raise NotImplementedError

  @abstractmethod
  def receive(self, packet: Packet) -> None:
    """Handle an incoming packet.

    Called by the channel after delivery (checksum already validated).
    Implementations should check ``packet.src`` if they need to filter by
    sender.
    """
    raise NotImplementedError
  
  def snapshot(self) -> List:
    """Return a fixed-width list of integer metrics for analytics.

    Called periodically by the simulator when ``track_analytics=True``.
    Override to expose protocol-level metrics (e.g. window size, RTO).
    All nodes in a network must return lists of the same length so that
    :meth:`~src.network_sim.NetworkSim.sum_analytics_matrix` can aggregate them.
    Would be worth allowing for less rigid structure but works well enough for now.
    """
    return []

  def validate_packet(self, packet: Packet) -> bool:
    """Return ``True`` if *packet* should be delivered to :meth:`receive`.

    The default implementation accepts all packets.  Override to add
    application-level filtering (e.g. reject packets from unknown senders).
    The channel-level CRC checksum is always verified *before* this method
    is called.
    """
    return True

  def set_timer(self, delay: int, callback: Callable, *args, **kwargs) -> None:
    """Schedule *callback* to fire *delay* ms from now.

    Thin wrapper around :meth:`~src.network.Network.schedule_after`.  Protocol
    code should prefer this helper over accessing ``self.network`` directly.
    """
    self.network.schedule_after(delay, callback, *args, **kwargs)
