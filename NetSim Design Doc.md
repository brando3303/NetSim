NetSim Design Doc

Goal: Create a discrete time simulated network of nodes connected bidirectionally through a channel which simulates packet loss, reorders, transmission time, and bitrate. NetSim’s purpose is to test various protocols over an unreliable network. The simulation is deterministic by seed (ties, reordering)

NetworkSim: event manager which have no connection to the system it is simulating. Progresses time.

* Fields  
  * network: Network  
    * The network to be simulated  
    * Initialized empty   
  * eventQueue: PriorityQueue\<Event, int\>  
    * A priority queue which holds events as values and times as keys, and executes the lowest time event when that event is popped from the queue during runtime.   
    * Initialized empty  
  * time: int  
    * The current clock time of the network (ms), updated when an event is popped off the eventQueue  
    * Initialized 0  
  * running: boolean  
    * Keeps track of if the simulation has started (start() was called)  
    * Initialized false  
  * seed: int  
    * Set at initialization  
    * Used to calculate RNG for deterministic simulation  
* Methods  
  * start()  
    * Calls network.init(). Sets running to true. Calls network.start()  
    * Begins a loop while running is true and eventQueue is non-empty:  
      * Dequeue (event, eventTime) from eventQueue  
      * Set time to eventTime  
      * Handle event:  
        * Event \=\> event.callback(time, event.args)   
  * scheduleAt(Event, eventTime):  
    * If eventTime \< time then return. Else, add (eventTime, event) to eventQueue.  
  * scheduleIn(event, delay):  
    * Add (time \+ delay, event) to eventQueue

Network: an interface for interacting with the simulator

* Fields  
  * name: string  
    * Default “1”  
  * networkSim: NetworkSim  
    * The simulator that this network is a part of  
    * Initialized null  
  * nodes: List\<Node\>  
    * The list of nodes that are members of this channel. They are Initialized and started at runtime. Populated before simulation starts.  
    *  Initialized empty  
  * channels: List\<Channel\>  
    * The channels within this network.  
    * Initialized empty  
* Methods  
  * init():  
    * Initializes all nodes. Calls node.init() on each node in nodes  
  * start():   
    * calls node.start() on all nodes in nodes  
  * end():   
    * ends the simulation and cleans eventQueue  
  * scheduleAt(event, time):  
    * Call networkSim.scheduleAt(event, time)  
  * scheduleIn(event, delay):  
    * Call networkSim.scheduleIn(event, time)  
  * now():  
    * Return networkSim.time

Channel: many to many connection between nodes. A node must call channel.send() to send a message to any other node

* Fields  
  * network: Network  
    * The network that this channel belongs to  
    * Initialized null  
  * nodes: List\<Node\>  
    * The nodes that this channel links together  
    * Initialized empty  
  * packetQueue: FIFOQueue\<Packet\>  
    * A fifo queue which holds which packet should be sent next over the channel. Its limits are determined by maxQueueLength  
    * Initialized empty  
  * maxQueueLength: int  
    * The maximum length in bytes of the queue  
    * Initialized inf  
  * nextTransmitTime: int  
    * The next time that the channel will be free. Set when a packet finishes transmitting and a EndTransmit event is triggered  
    * Initialized 0  
  * bitRate: int  
    * Number of bits that can pass through the channel per second. Used to determine transmission time  
    * Initialized 4Mbps  
  * propogationDelay: int  
    * Number of ms that packets spend on the wire  
    * Initialized to 100ms  
  * errorRate: int  
    * Percent of packets that should have errors on average  
  * averageError: int  
    * Average number of bit errors per errored message  
  * delayVariance: int   
    * Variance of delay in ms that should be added the packets  
  *   
* Methods  
  * addNode(Node):   
    * adds the inputted node to the nodes list. Adds self to Node’s channel list Can only be called before simulation starts  
  * send(Packet):   
    * Process packet: serializes packet.  
    * Add to packetQueue if possible:   
      * If packetQueue is full, drop this packet.  
      * If packetQueue is empty, add packet to packetQueue, and call network.scheduleIn(StartTransmit, 0\) to eventQueue.  
      *  Otherwise, add it to packetQueue  
  * handleStartTransmit(time):    
    * peek packet from packetQueue. If empty return. Otherwise, Calculate endTransmitTime (max(time, nextTransmitTime) \+ packetLength/bitRate	), call network.scheduleAt(EndTransmit, endTransmitTime). Set nextTransmitTime to endTransmitTime  
  * handleEndTransmit(time):   
    * dequeue packet from packetQueue, add errors if any, call network.scheduleAt(ReceivePacket(packet), time \+ propagationDelay \+ noise). If packetQueue is non-empty, call network.scheduleAt(StartTransmit, time).  
  * handleReceivePacket(time, packet):  
    * If dest in nodes  
    * Call dest.receive(packet) 

Interface Node

* Fields  
  * name: string  
    * Name of this node, should be unique  
  * channels: List\<Channel\>  
    * The channels that this node is a part of. Set when added to a channel  
  * network: Network  
    * The network that this node is a part of  
* Methods  
  * Abstract init()  
    * Called by Channel before the channel starts  
  * Abstract start()  
    * Called after Channel has started. Ordering will be random determined by seed  
  * Abstract receive(packet)  
    * Receives a packet and processes it  
  * setTimer(TimerFunction, args, ms)  
    * Call network.scheduleIn((TimerFunction, args), ms). TimerFunction(args) is called when the timer runs out. 

Data Types

* Packet  
  * Fields  
    * Source: string  
    * Dest: string  
    * Size: int  
    * Data: byte\[\]  
* Event  
  * Fields  
    * Callback: (time, args…) \-\> void  
    * Args: any\[\]  
* EventCallback(time, args…)