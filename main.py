import matplotlib.pyplot as plt
import numpy as np


from src.index import NetworkSim, Network, Node, Channel, Packet

class SARNode(Node):
     #send and recieve node
  def __init__(self, name: str):
     super().__init__(name)
     self.messages = 0
  
  def start(self):
    print(f"starting {self.name}")
    self.channels[0].send(Packet("Hello, World!", self.name, "Node 2"))
    self.network.schedule_after(1000, self.send_timer_message)


  def receive(self, packet):
    if self.messages < 7:
      print(f"{self.name} received packet: {packet.data} from {packet.src}")
      self.channels[0].send(Packet("Ack", self.name, "Node 2"))
      self.messages += 1

  def send_timer_message(self):
    self.channels[0].send(Packet("Timer message", self.name, "Node 2"))


def main() -> None:
  print("starting simulation")

  # option one
  ns = NetworkSim(seed=42, logging=True)
  net = Network(ns) #pc net.netsim = ns
  node1 = SARNode("Node 1") #pc node1.net = none
  node2 = SARNode("Node 2")
  net.add_node(node1) #pc net.nodes = [node1]
  net.add_node(node2) #pc net.nodes = [node1, node2]
  channel = Channel(bitRate=1000*8, propogationDelay=0) #pc channel.net = none
  net.add_channel(channel) #pc net.channels = [channel]
  channel.add_node(node1) #pc channel.nodes = [node1]
  channel.add_node(node2) #pc channel.nodes = [node1, node2], node1.channels = [channel], node2.channels = [channel]
  ns.start() #pc net.init(), net.start(), ns.simulation_loop()

  print("simulation finished")



if __name__ == "__main__":
	main()
