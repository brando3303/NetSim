
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from . import packet as pkt

if TYPE_CHECKING:
  from .node import Node
  from .network import Network
  from .packet import Packet

BROADCAST_ID = 0xFFFFFFFF

class Channel:
  def __init__(self, max_queue_length=100,
               bit_rate=1000, 
               propagation_delay=100, 
               error_rate=0, 
               average_error=0, 
               delay_variance=0):
    self._network: Network | None = None
    self.nodes: dict[int, Node] = {}
    self.packet_queue = deque()
    self.max_queue_length = max_queue_length
    self.next_transmit_time = 0
    self.bit_rate = bit_rate
    self.propagation_delay = propagation_delay
    self.error_rate = error_rate
    self.average_error = average_error
    self.delay_variance = delay_variance
    self._current_drops: int = 0
    self._current_throughput: int = 0

  @property
  def network(self):
    if self._network is None:
      raise RuntimeError("Channel is not attached to a network")
    return self._network

  @network.setter
  def network(self, value):
      if value is None:
          raise ValueError("network cannot be None")
      self._network = value

  def add_node(self, node: Node):
    self.nodes[node.name] = node
    if self not in node.channels:
      node.channels.append(self)

  def send(self, packet: pkt.Packet):
    packet_bytes = pkt.encode_packet(packet)

    if len(self.packet_queue) >= self.max_queue_length: #TODO check byte length of queue instead of packet count
      self._record_drop()
      return
    if len(self.packet_queue) == 0:
      self.packet_queue.append(packet_bytes)
      self.network.schedule_after(0, self.handle_start_transmit)
    else:
      self.packet_queue.append(packet_bytes)


  # Event Handlers

  def handle_start_transmit(self):
    if len(self.packet_queue) == 0:
      return
    packet_bytes = self.packet_queue[0]
    transmit_time = round(len(packet_bytes) * 8 / (self.bit_rate / 1000))
    self.network.schedule_after(transmit_time, self.handle_end_transmit)

  def handle_end_transmit(self):
    if len(self.packet_queue) == 0:
      return
    packet_bytes = self.packet_queue.popleft()
    final_prop_delay = self.propagation_delay + round(abs(self.network.gauss(0, self.delay_variance)))
    self.network.schedule_after(final_prop_delay, self.handle_receive_packet, packet_bytes)
    if len(self.packet_queue) > 0:
      self.network.schedule_after(0, self.handle_start_transmit)

  def handle_receive_packet(self, packet_bytes: bytes):
    packet_bytes = self._inject_byte_errors(packet_bytes)

    if not pkt.validate(packet_bytes):
      self._record_drop()
      return

    try:
      packet = pkt.decode_packet(packet_bytes, validate_checksum=False)
    except ValueError:
      self._record_drop()
      return

    if packet.dst == BROADCAST_ID:
      delivered_any = False
      for node_id, node in self.nodes.items():
        if node_id == packet.src:
          continue 
        if node.validate_packet(packet):
          node.receive(packet)
          delivered_any = True
      if not delivered_any:
        self._record_drop()
      else:
        self._record_throughput()
      return

    node = self.nodes.get(packet.dst)
    if node is None:
      self._record_drop()
      return
    
    if node.validate_packet(packet):
      node.receive(packet)
      self._record_throughput()
      return

    self._record_drop()

  # Error injection helpers

  def _error_probability(self) -> float:
    # Accept either [0,1] ratio or [0,100] percent.
    if self.error_rate <= 0:
      return 0.0
    if self.error_rate <= 1:
      return float(self.error_rate)
    return min(1.0, float(self.error_rate) / 100.0)

  def _choose_error_count(self) -> int:
    if self.average_error <= 0:
      return 1
    count = round(abs(self.network.gauss(self.average_error, max(1.0, self.average_error / 2))))
    return max(1, count)

  def _inject_byte_errors(self, packet_bytes: bytes) -> bytes:
    probability = self._error_probability()
    if probability <= 0 or self.network.random() >= probability:
      return packet_bytes

    corrupted = bytearray(packet_bytes)
    if len(corrupted) == 0:
      return packet_bytes

    error_count = min(self._choose_error_count(), len(corrupted))
    for _ in range(error_count):
      index = self.network.randint(0, len(corrupted) - 1)
      original = corrupted[index]
      new_value = original
      while new_value == original:
        new_value = self.network.randint(0, 255)
      corrupted[index] = new_value

    return bytes(corrupted)

  def _record_drop(self):
    self._current_drops += 1

  def _record_throughput(self):
    self._current_throughput += 1

  # Analytics

  def snapshot(self) -> list[int]:
    """Return [throughput, drops] since last snapshot and reset counters."""
    result = [self._current_throughput, self._current_drops]
    self._current_throughput = 0
    self._current_drops = 0
    return result
