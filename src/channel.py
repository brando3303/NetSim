"""Simulated communication channel for NetSim.

A :class:`Channel` models a shared physical medium between two or more nodes.
It applies three layers of network impairment in order:

1. **Queue overflow** — packets arriving when the TX queue is full are dropped.
2. **Transmission delay** — each packet occupies the medium for
   ``ceil(packet_bits / bit_rate)`` ms before it starts propagating.
3. **Propagation delay + jitter** — after transmission completes, the packet
   is scheduled to arrive at destination nodes after a (possibly varying)
   propagation delay drawn from a Gaussian distribution.
4. **Byte-level errors** — with probability ``error_rate``, a random number of
   bytes are corrupted before the CRC-32 is verified; corrupted packets are
   dropped at the receiver.

Delivery semantics:

* *Unicast*: the packet is delivered to ``nodes[dst]`` if that node is
  registered on this channel.
* *Broadcast* (``dst == BROADCAST_ID``): delivered to every node except the
  sender.

All timing is in milliseconds.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Callable

from . import packet as pkt

if TYPE_CHECKING:
  from .node import Node
  from .network import Network
  from .packet import Packet

#: Special destination address that delivers a packet to all nodes on the channel
#: except the sender.  Stored as a uint32 (all bits set = 0xFFFFFFFF).
BROADCAST_ID = 0xFFFFFFFF

class Channel:
  """Simulated point-to-multipoint communication channel.

  Attributes:
      max_queue_length:    Maximum number of packets that can be queued for
                           transmission.  Excess packets are dropped.
      bit_rate:            Transmission rate in bits per second.
      propagation_delay:   Base one-way propagation delay in ms (ignored when
                           ``propagation_delay_fn`` is set).
      propagation_delay_fn: Optional callable ``f(sim_time_ms) -> delay_ms``
                            that returns a time-varying propagation delay.
                            Takes precedence over ``propagation_delay``.
      error_rate:          Probability (0–1 or 0–100) that a given packet is
                           subjected to byte corruption.
      average_error:       Mean number of bytes to corrupt when an error is
                           injected (Gaussian, clamped to at least 1).
      delay_variance:      Standard deviation (ms) of Gaussian jitter added to
                           each propagation delay sample.
  """
  def __init__(
      self,
      max_queue_length: int = 100,
      bit_rate: int = 1000,
      propagation_delay: int = 100,
      error_rate: float = 0,
      average_error: float = 0,
      delay_variance: float = 0,
      propagation_delay_fn: Callable[[int], int | float] | None = None,
  ):
    """Create a channel with the given impairment parameters.

    Args:
        max_queue_length:    Queue capacity in packets.
        bit_rate:            Transmission rate in bits per second.
        propagation_delay:   Base propagation delay in ms (ignored if
                             ``propagation_delay_fn`` is provided).
        error_rate:          Packet error probability.  Accepts either a ratio
                             in [0, 1] or a percentage in (1, 100].  A value of
                             0 disables error injection.
        average_error:       Mean number of bytes to corrupt per error event.
                             When 0, exactly one byte is corrupted.
        delay_variance:      Standard deviation (ms) of Gaussian jitter applied
                             to each propagation delay sample.
        propagation_delay_fn: Time-varying propagation delay function.  Receives
                              the current simulation time in ms and returns a
                              delay in ms.  Overrides ``propagation_delay``.
    """
    self._network: Network | None = None
    self.nodes: dict[int, Node] = {}
    self.packet_queue: deque = deque()
    self.max_queue_length = max_queue_length
    self.bit_rate = bit_rate
    self.propagation_delay = propagation_delay
    self.propagation_delay_fn = propagation_delay_fn
    self.error_rate = error_rate
    self.average_error = average_error
    self.delay_variance = delay_variance
    # Per-snapshot counters reset by snapshot().
    self._current_drops: int = 0
    self._current_throughput: int = 0

  @property
  def network(self) -> Network:
    if self._network is None:
      raise RuntimeError("Channel is not attached to a network")
    return self._network

  @network.setter
  def network(self, value: Network) -> None:
      if value is None:
          raise ValueError("network cannot be None")
      self._network = value

  def add_node(self, node: Node) -> None:
    """Register *node* on this channel and add this channel to ``node.channels``."""
    self.nodes[node.name] = node
    if self not in node.channels:
      node.channels.append(self)

  def send(self, packet: pkt.Packet) -> None:
    """Enqueue *packet* for transmission.

    If the TX queue is already at capacity the packet is silently dropped and
    the drop counter is incremented.  If the queue was previously empty, a
    ``handle_start_transmit`` event is scheduled immediately (delay=0) so the
    packet begins occupying the medium on the next event-loop iteration.

    Note:
        The queue depth is measured in *packets*, not bytes.
        # TODO: consider switching to a byte-budget queue for more realistic
        #       buffer pressure modeling.
    """
    packet_bytes = pkt.encode_packet(packet)

    if len(self.packet_queue) >= self.max_queue_length:
      self._record_drop()
      return
    if len(self.packet_queue) == 0:
      self.packet_queue.append(packet_bytes)
      self.network.schedule_after(0, self.handle_start_transmit)
    else:
      self.packet_queue.append(packet_bytes)


  # ------------------------------------------------------------------ #
  # Event handlers (called by the simulator)                             #
  # ------------------------------------------------------------------ #

  def handle_start_transmit(self) -> None:
    """Begin transmitting the front-of-queue packet.

    Computes the transmission time from the packet size and bit rate, then
    schedules ``handle_end_transmit`` when the last bit leaves the wire.
    """
    if len(self.packet_queue) == 0:
      return
    packet_bytes = self.packet_queue[0]
    # transmission_time_ms = (packet_bits) / (bit_rate_bps / 1000)
    transmit_time = round(len(packet_bytes) * 8 / (self.bit_rate / 1000))
    self.network.schedule_after(transmit_time, self.handle_end_transmit)

  def handle_end_transmit(self) -> None:
    """Pop the just-transmitted packet and schedule its arrival at receivers.

    Adds Gaussian jitter (``|N(0, delay_variance)|``) on top of the base
    propagation delay so that consecutive packets arrive at slightly different
    times.  If more packets are waiting in the queue, immediately starts
    transmitting the next one (delay = 0).
    """
    if len(self.packet_queue) == 0:
      return
    packet_bytes = self.packet_queue.popleft()
    base_delay = self._resolve_propagation_delay()
    # Jitter is the absolute value of a zero-mean Gaussian so that the delay
    # is always non-negative and symmetric around the base propagation delay.
    final_prop_delay = base_delay + round(abs(self.network.gauss(0, self.delay_variance)))
    self.network.schedule_after(final_prop_delay, self.handle_receive_packet, packet_bytes)
    if len(self.packet_queue) > 0:
      self.network.schedule_after(0, self.handle_start_transmit)

  def _resolve_propagation_delay(self) -> int:
    """Return the propagation delay in ms for the current simulation time.

    Uses ``propagation_delay_fn`` when provided; otherwise returns the static
    ``propagation_delay`` value.  The result is always clamped to >= 0.
    """
    if self.propagation_delay_fn is None:
      return max(0, int(self.propagation_delay))

    delay_value = self.propagation_delay_fn(int(self.network.sim.time))
    return max(0, int(round(delay_value)))

  def handle_receive_packet(self, packet_bytes: bytes) -> None:
    """Deliver a packet to its destination node(s) after propagation delay.

    Steps:
    1. Optionally inject byte errors (controlled by ``error_rate``).
    2. Validate the CRC-32 checksum; drop the packet if it fails.
    3. Deserialize the packet header to read ``dst``.
    4. Deliver to the destination node (unicast) or all non-source nodes
       (broadcast).  Drop if the destination node is not on this channel.
    5. Call the node's ``validate_packet`` hook before calling ``receive``.
    """
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

  # ------------------------------------------------------------------ #
  # Error injection helpers                                              #
  # ------------------------------------------------------------------ #

  def _error_probability(self) -> float:
    """Normalize ``error_rate`` to a probability in [0.0, 1.0].

    Accepts either a ratio in [0, 1] or a percentage in (1, 100].
    """
    # Accept either [0,1] ratio or [0,100] percent.
    if self.error_rate <= 0:
      return 0.0
    if self.error_rate <= 1:
      return float(self.error_rate)
    return min(1.0, float(self.error_rate) / 100.0)

  def _choose_error_count(self) -> int:
    """Sample the number of bytes to corrupt for this error event."""
    if self.average_error <= 0:
      return 1
    count = round(abs(self.network.gauss(self.average_error, max(1.0, self.average_error / 2))))
    return max(1, count)

  def _inject_byte_errors(self, packet_bytes: bytes) -> bytes:
    """Randomly corrupt bytes in *packet_bytes* according to ``error_rate``.

    Each corrupted byte is replaced with a value guaranteed to differ from
    the original, so a single-byte error always changes the byte.  This
    ensures the CRC-32 check will catch the corruption.
    """
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
      # Spin until we land on a value different from the original byte.
      while new_value == original:
        new_value = self.network.randint(0, 255)
      corrupted[index] = new_value

    return bytes(corrupted)

  def _record_drop(self) -> None:
    self._current_drops += 1

  def _record_throughput(self) -> None:
    self._current_throughput += 1

  # ------------------------------------------------------------------ #
  # Analytics                                                            #
  # ------------------------------------------------------------------ #

  def snapshot(self) -> list[int]:
    """Return ``[throughput, drops]`` since the last snapshot and reset counters.

    Called periodically by the simulator when ``track_analytics=True``.
    Both counters are reset to zero after each snapshot so that each
    analytics window reflects only the activity in that interval.
    """
    result = [self._current_throughput, self._current_drops]
    self._current_throughput = 0
    self._current_drops = 0
    return result
