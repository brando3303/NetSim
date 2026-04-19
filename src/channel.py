
from __future__ import annotations


import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from .node import Node
  from .network import Network
  from .packet import Packet


class Channel:
  def __init__(self, maxQueueLength=100,
               bitRate=1000, 
               propogationDelay=100, 
               errorRate=0, 
               averageError=0, 
               delayVariance=0):
    self._network: Network | None = None
    self.nodes = []
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
    self.nodes.append(node)
    node.channels.append(self)

  def send(self, packet: Packet):
    # TODO serialize packet

    if len(self.packetQueue) >= self.maxQueueLength: #TODO check byte length of queue instead of packet count
      return
    if len(self.packetQueue) == 0:
      self.packetQueue.append(packet)
      self.network.schedule_after(0, self.handle_start_transmit)
    else:
      self.packetQueue.append(packet)

  def handle_start_transmit(self):
    if len(self.packetQueue) == 0:
      return
    packet = self.packetQueue[0]
    # TODO add error rate and delay variance
    transmitTime = round(len(packet.data) * 8 / (self.bitRate / 1000))
    self.network.schedule_after(transmitTime, self.handle_end_transmit)

  def handle_end_transmit(self):
    if len(self.packetQueue) == 0:
      return
    packet = self.packetQueue.pop(0)
    self.network.schedule_after(self.propogationDelay, self.handle_receive_packet, packet)
    if len(self.packetQueue) > 0:
      self.network.schedule_after(0, self.handle_start_transmit)

  def handle_receive_packet(self, packet: Packet):
    for node in self.nodes:
      node.receive(packet)
