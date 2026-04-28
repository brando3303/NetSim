Sliding Window Selective Acknowledgment

Goal: Create a reliable protocol for transmitting multi packet payloads between nodes that makes progress efficiently despite delays, reorders, duplicates, and drops. Use a sliding window protocol to maintain multiple packets in flight for higher resource use and faster transmit times, as well as selective acknowledgment to reduce the number of retransmissions necessary during congestion.

SWSACKServer

* Fields  
  * seqSpace: int  
    * The number of sequence numbers used before wrap around  
    * Default 256  
  * windowSize:   
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
  * retransmitTimeout: int   
    * Length of retransmitTimer  
* Methods  
  * start():  
    * For i in \[windowSize\]  
      * If (nd=nextData()) \!= \[\]  
        * sendFrame(SWPacket(i, nd))  
        * LFS \= (LFS \+ 1)%seqSpace  
  * receive(packet):  
    *  If packet is not instance of SackPacket return  
    * Otherwise call handleAckPacket(decodeSackPacket(packet))  
  * handleAckPacket(ack, sackBlocks):  
    * If \!isInWindow(ack.seqNum), return  
    * Otherwise, call processAck(ack)   
    * for each sackBlock in sackBlocks  
      * Call processSackBlock(sackBlock)  
    * Call updateWindow()  
    * If sackBlocks.length \> 0  
      * retransmitNextBlock()  
  * processAck(ack):  
    * ackBlock((LAS \+ 1\) % seqSpace, ack.seqNum)  
    * If window\[ack.seqNum\] does not exist, return  
    * set window\[ack.seqnum\] \= (True, ” )  
  * processSackBlock(sackBlock):  
    * ackBlock(sackBlock)  
    *   
  * decodeSackPacket(Packet):  
    * Decodes and returns the Ack and SackBlock\[\] within this packet  
  * updateWindow():  
    * While window\[(LRA \+ 1\) % seqSpace\].acked \== true  
      * LRA \= (LRA \+ 1\) % seqSpace  
      * window.delete(LRA)  
      * If data.length \- dataIndex \> 0  
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
    * scheduleAfter(retransmitTimeout, retransmitTimer, (packet.seqNum))  
    * If not exists, add window\[packet.seqNum\] \= (False, packet)  
  * retransmitTimer(seqNum)  
    * If \!isInWindow(seqNum) Or window\[seqNum\] does not exist Or window\[seqNum\]=(True, “) , return  
    * Otherwise   
      * channel.send(window\[seqNum\].packet)  
      * scheduleAfter(retransmitTimeout, retransmitTimer, (packet.seqNum))  
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
  * retransmitNextBlock()  
    * Retransmits only the first block of unacked packets in this window, following a similar algorithm to RFC 6675 Pipe algorithm. Should only be called when there is a Sack block in the ack packet. Otherwise this will resend the entire window  
    * i \=(LRA \+ 1)%seqSpace  
    * inUnackedBlock \= window\[i\].acked \== False  
    * While inUnackedBlock and i \!=( LFS \+ 1)%seqSpace:  
      * sendFrame(window\[i\].packet)  
      * i \=(i \+ 1\) % seqSpace  
      * If \!isInWindow(i), break  
      * inUnackedBlock \=  \!window\[i\].acked

SWSACKClient

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