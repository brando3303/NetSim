
from __future__ import annotations


from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from .node import Node
  from .network import Network
  from .packet import Packet

BROADCAST_ID = 0xFFFFFFFF

class Channel:
  def __init__(self, maxQueueLength=100,
               bitRate=1000, 
               propogationDelay=100, 
               errorRate=0, 
               averageError=0, 
               delayVariance=0):
    self._network: Network | None = None
    self.nodes: dict[int, Node] = {}
    self.packetQueue = []
    self.maxQueueLength = maxQueueLength
    self.nextTransmitTime = 0
    self.bitRate = bitRate
    self.propogationDelay = propogationDelay
    self.errorRate = errorRate
    self.averageError = averageError
    self.delayVariance = delayVariance

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

  def add_node(self, node: Node):
    self.nodes[node.name] = node
    if self not in node.channels:
      node.channels.append(self)

  def send(self, packet: Packet):
    packet_bytes = packet.to_bytes()

    if len(self.packetQueue) >= self.maxQueueLength: #TODO check byte length of queue instead of packet count
      return
    if len(self.packetQueue) == 0:
      self.packetQueue.append(packet_bytes)
      self.network.schedule_after(0, self.handle_start_transmit)
    else:
      self.packetQueue.append(packet_bytes)


  # Event Handlers

  def handle_start_transmit(self):
    if len(self.packetQueue) == 0:
      return
    packet_bytes = self.packetQueue[0]
    transmitTime = round(len(packet_bytes) * 8 / (self.bitRate / 1000))
    self.network.schedule_after(transmitTime, self.handle_end_transmit)

  def handle_end_transmit(self):
    if len(self.packetQueue) == 0:
      return
    packet_bytes = self.packetQueue.pop(0)
    final_prop_delay = self.propogationDelay + round(abs(self.network.gauss(0, self.delayVariance)))
    self.network.schedule_after(final_prop_delay, self.handle_receive_packet, packet_bytes)
    if len(self.packetQueue) > 0:
      self.network.schedule_after(0, self.handle_start_transmit)

  def handle_receive_packet(self, packet_bytes: bytes):
    from .packet import Packet

    packet_bytes = self._inject_byte_errors(packet_bytes)

    try:
      packet = Packet.from_bytes(packet_bytes)
    except ValueError:
      return

    if packet.dst == BROADCAST_ID:
      for id, node in self.nodes.items():
        if id == packet.src:
          continue 
        if node.validate_packet(packet):
          node.receive(packet)
      return

    node = self.nodes.get(packet.dst)
    if node is None:
      return

    if node.validate_packet(packet):
      node.receive(packet)


  # Error injection helpers

  def _error_probability(self) -> float:
    # Accept either [0,1] ratio or [0,100] percent.
    if self.errorRate <= 0:
      return 0.0
    if self.errorRate <= 1:
      return float(self.errorRate)
    return min(1.0, float(self.errorRate) / 100.0)

  def _choose_error_count(self) -> int:
    if self.averageError <= 0:
      return 1
    count = round(abs(self.network.gauss(self.averageError, max(1.0, self.averageError / 2))))
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


