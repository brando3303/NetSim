Congestion Control

Goal: implement additional protocol over sliding window sack and adaptive timeout to respond to changes in network condition. In particular, we include congestion window (cwnd) controlled by AIMD, and slow start before AIMD begins, as well as fast retransmit to avoid spurious timeouts when possible. These protocols together will make the end to end data transmission efficient despite random changes in the network condition and will prevent a single node from being the cause of congestion over a busy channel/link/network. 

Purpose: Congestion Controlled transmission on top of sliding window, SACK, and adaptive timeout is a simplified, yet still robust, implementation of the regular TCP stack commonly used in systems today. It is hoped that this can aid in analysing TCP from a deterministic, easily simulated lens to demonstrate theoretical limits in action and to identify edge cases where further improvements could be made. TCP as it is today is a standard which has evolved significantly since its conception in the 80s, which could not have taken into account the current state of the internet, as well as its diversity. This design doc and implementation aims to be a starting point for further exploration.

**TCPServer**  
Fields

* Sliding Window/SACK  
  * seqSpace: int  
    * The number of sequence numbers used before wrap around  
    * Default 256  
  * maxWindowSize:   
    * the size of the sliding window for this node. This must be less than half the seqSpace  
    * Set at initialization.    
  * window: HashMap\<int, (Bool, Packet)\>  
    * Maps sequenceNums to packets and whether they have been acked by the receiver  
    * It is updated as packets are sent and as they are acked  
    * Initialized empty  
  * (LAR) lastAckRecieved: int  
    * The sequence number of the last in order ack received. Updated when an ack of lastAckReceived+1 arrives  
    * Initialized to 0  
  * (LFS) lastFrameSent: int  
    * The last packet sequence number that was sent to the receiver. Updated when the sliding window moves and more frames are sent  
  * receiver: int  
    *  the name of the destination node. This node should be a SWSACKClient for progress to be made  
    * Set at construction  
  * data: Byte\[\]  
    * The data that will be sent by the server to the client  
    * Set at construction  
  * dataIndex: int   
    * Where in the data we have sent up to  
  * frameSize: int  
    * The max number of bytes that can be sent per frame  
* Adaptive Timeout  
  * RTO: int   
    * Length of retransmitTimer  
    * Will be calculated from SRRT and Svar when acks arrive   
  * SRRT (smoothedRoundTripTime) int  
    * The current moving average of roundtrip times encountered from acks  
    * Init \-1  
  * Svar (smoothedVariance): int  
    * Moving average of variance of roundtrip times  
    * Init \-1  
  * minRTO: int  
    * Minimum value for retransmitionTimeout  
    * Default 100 ms  
  * maxRTO: int  
    * Maximum value for retransmissionTimeout  
    * Default 60,000 ms  
  * firstCalc: boolean  
    * Whether smoothed RRT variables have been calculated for the first time  
    * Init false  
* Fast Retransmit/ Fast Recovery  
  * lastSeqAcked: int  
    * The last seqNum that was acked. Helps track if the same ack has been seen 3 times  
    * Init \-1  
  * repeatAckCount: int  
    * The number of repeat seq nums seen  
    * Init 0  
* Congestion Window/ AIMD  
  * congestionWindow: int  
    * The current size of the congestion window, increases and decreases throughout the runtime of the node  
    * Init 1  
* Slow Start  
  * inSlowStart: boolean  
    * Whether or not the congestion window is in slow start phase  
    * Init true  
  * congestionThreshold: int  
    * The last congestion window size before a timeout, divided by 2\. Used as a target window size during slow start before entering AIMD  
    * Initialized to inf?  
* Methods  
  * start():  
    * We start transmission by sending as many packets as our window allows (1 at start) and then starting a timer for the very first packet sent  
    * For i in \[eWin()\]  
      * If (nd=nextData()) \!= \[\]  
        * sendFrame(SWPacket(i, nd))  
        * LFS \= (LFS \+ 1)%seqSpace  
    * network.scheduleAfter(retransmissionTimeout, retransmitTimer((LAS+1)%seqSpace))  
  * (eWin()) effectiveWindow():  
    * Returns the effective window to use  
    * Return min(congestionWindow, maxWindowSize)  
  * receive(packet):  
    *  If packet is not instance of SackPacket return  
    * Otherwise call handleAckPacket(decodeSackPacket(packet))  
  * handleAckPacket(ack, sackBlocks):  
    * call processAck(ack)   
    * for each sackBlock in sackBlocks  
      * Call processSackBlock(sackBlock)  
    * Call updateWindow()  
  * processAck(ack):  
    * Processing an ack involves the following steps  
      * Check if this is a duplicate ack, and if it is the same duplicate ack as lastSeenAck, update count/ call fast retransmit, fast recovery  
      * If it is the next ack expected, then we should ack it and move the window along. If we are in slow start, we should double cwnd. If we are in aimd then we should increment cwnd. When we increase cwnd we need to send any packets that are now in the window.  
      * If we have crossed cThresh we should end slow start  
      * Finally we should update rto if not retransmitted  
    * //fast retransmit/recovery/ end slow start  
    * If ack.seqNum \!= lastSeqAcked  
      * lastSeqAcked \= ack.seqNum  
      * repeatAckCount \= 0  
    * Else   
      * repeatAckCount++  
      * If repeatAckCount \== 3  
        * //fast retransmit \+ multiplicative decrease  
        * sendFrame(window\[(LAR \+1)%seqSpace\].packet)  
        * repeatAckCount \= 0  
        * mdwindow()  
        * If inSlowStart  
          * inSlowStart \= false  
    * If window\[ack.seqNum\] does not exist, return // if there is no packet to ack then this must be old  
    * // at this point we know ack is for a packet in window \!= LAS, so it will move the window forward.  
    * If inSlowStart  
      * cwnd \= min(cwnd+1, maxWindowSize) //increase by more each time  
      * If cwnd \>= cThresh  
        * inSlowStart \= false  
    * Else   
      * Cwnd \= min(cwnd+1, maxWindowSize) //linear increase  
    * If \!window\[ack.seqNum\].retransmitted && \!window\[ack.seqNum\].acked  
      * updateTimeout(network.time \- window\[seqNum\].timeSent)  
    * ackBlock((LAS \+ 1\) % seqSpace, ack.seqNum) // set acked up to this packet  
    * set window\[ack.seqnum\].acked \= true  
  * processSackBlock(sackBlock):  
    * ackBlock(sackBlock)  
  * decodeSackPacket(Packet):  
    * Decodes and returns the Ack and SackBlock\[\] within this packet  
  * updateWindow():  
    * Slide window as far as possible, ensure all packets in eWin are sent.  
    * While window\[(LRA \+ 1\) % seqSpace\].acked \== true  
      * LRA \= (LRA \+ 1\) % seqSpace  
      * window.delete(LRA)  
    * While (LFS+1)%seqSpace \!= (LAS \+ eWin()+1)%seqSpace && data.length \- dataIndex \> 0  
      * nd \= nextData()  
      * sendFrame(SWPacket((LFS \+ 1)%seqSpace, nd))  
      * LFS \= (LFS \+ 1\) % seqSpace  
  * nextData()  
    * If data.length \- dataIndex \> 0	  
      * payloadLen \= min(data.length \- dataIndex, frameSize)  
      * next \= data\[dataIndex : dataIndex \+ payloadLen\]  
      * dataIndex \+= payloadLen  
      * Return next  
    * Else return \[\]  
  * sendFrame(packet):  
    * channel.send(packet)  
    * If not exists, add window\[packet.seqNum\] \= (False, packet, retransmitted \= false)  
  * retransmitTimer(seqNum)  
    * Checks if this seqNum is still the earliest unacked packet, and if not does nothing. If so, then we backoff retransmit, backoff congestionThreshhold, set congestionWIndow to 1, and begin slowStart  
    * If \!isInWindow(seqNum) Or window\[seqNum\] does not exist Or window\[seqNum\]=(True, “) , return  
    * Otherwise   
      * channel.send(window\[seqNum\].packet)  
      * window\[seqNum\].retransmitted \= true  
      * RTO \= min(maxRTO, 2\* RTO)  
      * scheduleAfter(RTO, retransmitTimer, (seqNum))  
      * // cwnd  
      * cThresh \= cwnd/2  
      * Cwnd \= 1  
      * inSlowStart \= true  
  * isInWindow(seqNum):  
    * Convenience method to check if the seqNum is in the current window, taking into account wrap around.  
    * Return true if 0 \< (seqNum \- LAR)%seqSpace \<= windowSize  
  * seqDist(left, right)  
    * The distance between left and right seqNums, moving right around the seqSpace  
    * Return (right-left)%seqSpace  
  * ackBlock(SLE, SRE)  
    * i \= SLE  
    * While i \!= SRE  
      * If \!isInWindow(i): i++, continue  
      * Else, window\[i\].acked \= True  
      * I++  
  * updateTimeout(diff):  
    * Should be called when seqNum ack first arrives  
    * RRT \= diff  
    * Svar \= .9\*Svar \+ .1\*|SRRT \- RRT|  
    * SRRT \= .9\*SRRT \+ .1\*RRT  
    * RTO \= clamp(maxRTO, minRTO, SRRT \+ 4\*Svar)  
  * mdwindow()  
    * Multiplicative decrease cwnd. This is strictly a decrease so we can assume no new packets must be sent.  
    * Set cwnd \= cwnd/2

**TCPClient**

* Fields  
  * bufferWindowSize: int  
    * Size of the buffer window, should be the same size as windowSize of server  
  * server: int  
    * Name of server node to expect messages from  
  * Buffer: HashMap\<int, packet\>  
    * Holds packets that have arrived out of order and maps them to their sequence number. Updates when a packet arrives  
  * (LAS) lastAckSent: int   
    * The sequence number of the last in order ack sent  
    * Initialized to 0  
  * receivedData: List\<Byte\>  
    * Initialized empty  
  * seqSpace: int  
  * maxSackBlocks: int   
    * The number of sackBlocks that can be transmitted per ack  
    * Default 4  
* Methods  
  * Start()  
  * receive(packet)  
    * If not instance of SWPacket, return  
    * Else call handleSWPacket(packet)  
  * handleSWPacket(packet)  
    * If \!isInWindow(packet.seq)  
      * sendSack(LAS, \[\])   
    * Else if \!buffer\[seqNum\] exists, buffer\[packet.seqNum\] \= packet  
    * Call updateWindow()  
    * Call sendSack(LAS, generateSackBlocks())  
  * isInWindow(seqNum)  
    * Return true if 0 \< (seqNum \- LAS)%seqSpace \<= bufferWindowSize  
  * sendSack(seqNum, sackBlocks)  
    * channel.send(AckPacket(seqNum, sackBlocks)  
  * updateWindow()  
    * While buffer\[(LAS \+ 1\) % seqSpace\].packet exists  
      * LAS \= (LAS \+ 1\) % seqSpace  
      * receivedData.append(buffer\[LAS\])  
      * buffer.delete(LAS)  
  * generateSackBlock()  
    * Assumes that it is called after updateWindow, so that it sends updated information. In particular, it is reasonable to assume that the sequence number after LAS is not recieved  
    * i \= (LAS \+ 1)%seqSpace  
    * blocks \= \[\]  
    * inBlock \= false  
    * SLE, SRE \= 0   
    * While isInWindow(i) and blocks.length \< maxSackBlocks  
      * If \!inBlock  
        * If buffer\[i\] exists  
          * inBlock \= True  
          * SLE \= i  
      * If inBlock  
        * If buffer\[i\] does not exist  
          * inBlock \= false  
          * SRE \= i  
          * Blocks.append((SLE, SRE))  
      * i \= (i+1)%seqSpace  
    * If inBlock and blocks.length \< maxSackBlocks  
      * SRE \= i  
      * blocks.append((SLE,SRE))  
    * Return blocks

