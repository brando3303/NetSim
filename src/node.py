from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, List

if TYPE_CHECKING:
  from .network import Network
  from .packet import Packet

class Node(ABC):
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

  @abstractmethod
  def init(self):
    raise NotImplementedError

  @abstractmethod
  def start(self):
    raise NotImplementedError

  @abstractmethod
  def receive(self, packet: Packet):
    raise NotImplementedError
  
  def snapshot(self) -> List:
    return []

  def validate_packet(self, packet: Packet) -> bool:
    return True

  def set_timer(self, delay: int, callback: Callable, *args, **kwargs):
    self.network.schedule_after(delay, callback, *args, **kwargs)
      