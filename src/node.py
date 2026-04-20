from __future__ import annotations

from typing import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from .network import Network
  from .packet import Packet

class Node:
  def __init__(self, name: int):
    self.name = name
    self.channels = []
    self._network: Network | None = None

  @property
  def network(self):
    if self._network is None:
      raise RuntimeError("Node is not attached to a network")
    return self._network

  @network.setter
  def network(self, value):
      if value is None:
          raise ValueError("network cannot be None")
      self._network = value

  def init(self):
    pass

  def start(self):
    pass

  def receive(self, packet: Packet):
    pass

  def validate_packet(self, packet: Packet) -> bool:
    return packet.validate()

  def set_timer(self, delay: int, callback: Callable, *args, **kwargs):
    self.network.schedule_after(delay, callback, *args, **kwargs)
      