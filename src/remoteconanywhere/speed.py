'''
Action server that allows checking the speed.

Created on 12 avr. 2023

@author: Cedric


Protocol: client sends a time, server returns its time. Client calculates the time difference between first time and received time.
-> Latency

Then client sends messages of 100 bytes, 1000 bytes, 10000 bytes, 100000 bytes, 1000000 bytes.
Server sends each reception time and message size as a tuple
Client sends "NowYourTime"
Server sends the same messages in the same order. Client calculates the time differences.
Client sends "ThankYou" and disconnects.
'''

import pickle
import datetime
import logging, os
import threading
from remoteconanywhere.communication import ActionServer

LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))

CAPA_SPEED = 'speed'

class SpeedActionServer(ActionServer):
    NOW_SERVER_TIME = b"NowYourTime"
    THANK_YOU = b"ThankYou"
    
    def __init__(self):
        super().__init__(CAPA_SPEED)
    
    def start(self, session):
        ActionServer.start(self, session)
        threading.Thread(target=self.mainLoop, name="%s-%s" % (self.capability, session.sid), args=(session,)).start()
        
    def mainLoop(self, session):
        LOGGER.info("[Session %s] Started with %s", session.sid, session.other)
        
        # first time sent
        received = session.receiveChunkWait()
        clientDate = pickle.loads(received)
        serverDate = datetime.datetime.now()
        session.send(pickle.dumps(serverDate))
        
        # now receive data
        messages = []
        totalsize = 0
        starttime = datetime.datetime.now()
        while True:
            received = session.receiveChunkWait()
            if received == SpeedActionServer.NOW_SERVER_TIME:
                break
            messages.append(received)
            size = len(received)
            totalsize += size
            date = datetime.datetime.now()
            session.send(pickle.dumps((date, size)))
        
        endtime = datetime.datetime.now()
        LOGGER.info("[Session %s] Received %s messages of size %s in %s", session.sid, len(messages), totalsize, endtime-starttime)
        
        starttime = datetime.datetime.now()
        for mess in messages:
            session.send(mess)
        
        endtime = datetime.datetime.now()
        LOGGER.info("[Session %s] Send %s messages of size %s in %s", session.sid, len(messages), totalsize, endtime-starttime)
        
        received = session.receiveChunkWait()
        endtime = datetime.datetime.now()
        LOGGER.info("[Session %s] Received %s after %s", session.sid, received, endtime-starttime)
        session.close()

def runSpeedClient(session):
    '''Uses a client session to check the speed.'''
    LOGGER.info("Connected to %s to check the speed.", session.other)
    clientDate = datetime.datetime.now()
    session.send(pickle.dumps(clientDate))
    serverDate = pickle.loads(session.receiveChunkWait())
    clientDate2 = datetime.datetime.now()
    latency = (clientDate2 - clientDate)/2
    
    LOGGER.info("Latency: %s", latency)
    LOGGER.info("Server time: %s", serverDate)
    LOGGER.info("Time difference: %s", serverDate - (clientDate + latency))
    
    totalsizesent = 0
    totalsizeack = 0
    maxserverchunk = 0
    starttime = datetime.datetime.now()
    for messageslength in [2,3,4,5,6,7,6,5,4,3,2,3,4,5]:
        message = b"0"*(10**messageslength)
        totalsizesent += len(message)
        session.send(message)
    endtime = datetime.datetime.now()
    LOGGER.info("Sent %s bytes in %s", totalsizesent, endtime-starttime)
    
    lastserverdate = serverDate
    minspeed, maxspeed = 10**10, 0
    while totalsizeack < totalsizesent:
        received = session.receiveChunkWait()
        date, size = pickle.loads(received)
        totalsizeack += size
        
        maxserverchunk = max(maxserverchunk, size)
        deltatime = (date - lastserverdate).total_seconds()
        if deltatime == 0:
            LOGGER.warning("Strange infinite speed for size %s", size)
        else:
            localspeed = size / deltatime
            minspeed = min(minspeed, localspeed)
            maxspeed = max(maxspeed, localspeed)
        
        lastserverdate = date
    
    endtime = datetime.datetime.now()
    totaldeltatime = endtime-starttime
    LOGGER.info("Server received %s bytes (by max %s) in %s", totalsizesent, maxserverchunk, totaldeltatime)
    speedtotal = totalsizesent / totaldeltatime.total_seconds() if totaldeltatime.total_seconds() > 0 else "infinite"
    LOGGER.info("Upload speed: %sB/s (min: %sB/s, max: %sB/s)", speedtotal, minspeed, maxspeed)
    
    starttime = lastclientdate = datetime.datetime.now()
    session.send(SpeedActionServer.NOW_SERVER_TIME)
    totalsizeack = 0
    minspeed, maxspeed = 10**10, 0
    while totalsizeack < totalsizesent:
        received = session.receiveChunkWait()
        size = len(received)
        totalsizeack += size
        date = datetime.datetime.now()
        deltatime = (date - lastclientdate).total_seconds()
        if deltatime == 0:
            LOGGER.warning("Strange infinite speed for size %s", size)
        else:
            localspeed = size / deltatime
            minspeed = min(minspeed, localspeed)
            maxspeed = max(maxspeed, localspeed)
        
        lastclientdate = date
    
    endtime = datetime.datetime.now()
    totaldeltatime = endtime-starttime
    LOGGER.info("Client received %s bytes in %s", totalsizeack, totaldeltatime)
    speedtotal = totalsizesent / totaldeltatime.total_seconds() if totaldeltatime.total_seconds() > 0 else "infinite"
    LOGGER.info("Download speed: %sB/s (min: %sB/s, max: %sB/s)", speedtotal, minspeed, maxspeed)
    session.send(SpeedActionServer.THANK_YOU)
    session.close()

def main():
    '''Runs a speed server and a speed client'''
    from remoteconanywhere.communication import QueueCommunicationSession
    from threading import Thread
    logging.basicConfig(level='INFO', format='%(asctime)-15s %(levelname)-5s %(module)s.%(funcName)s [%(threadName)s] %(message)s')
    # create server
    actionserver = SpeedActionServer()
    # create sessions
    sessionS = QueueCommunicationSession('server')
    sessionC = QueueCommunicationSession('client')
    sessionS.inexorablyLinkQueue(sessionC)
    # start client and server
    actionserver.start(sessionS)
    client = runSpeedClient(sessionC)

if __name__ == '__main__':
    main()
