'''
Contains all is needed to create a communication with a socket on a remote machine

Created on 10 avr. 2020

@author: Cedric
'''

from remoteconanywhere.communication import ActionServer, CommunicationSession
import threading
import time
import socket
from select import select
import logging
import os

LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))

HEADER_CONNECTPB = b'UNABLETOCONNECT'
HEADER_CONNECTOK = b'ABLETOCONNECT'
HEADER_STOP = b'CLOSESOCKET'
HEADER_NORMAL = b'DATA'


class GenericTcpSocketActionServer(ActionServer):
    
    def __init__(self, capability='socket'):
        ActionServer.__init__(self, capability)
    
    def start(self, session):
        ActionServer.start(self, session)
        threading.Thread(target=self.mainLoop, name="%s-%s" % (self.capability, session.sid), args=(session,)).start()
    
    def createSocket(self, session):
        '''Creates the socket that will be given by the session.
        In the first chunk, one line: hostname
        second line: port
        
        IF OK, sends to session HEADER_CONNECTOK,
        Otherwise sends to session HEADER_CONNECTPB + problem'''
        while not session.checkIfDataAvailable():
            time.sleep(0.01)
        data = session.receiveChunk().decode()
        lines = [l.trim() for l in data.split('\n')]
        # first line for the hostname
        hostname = lines[0]
        try:
            port = int(lines[1])
            # TODO: add cwd and environment
            LOGGER.debug("Starting connexion to %s:%s", hostname, port)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(0)
            sock.connect((hostname, port))
        except Exception as e:
            LOGGER.warning("Impossible to connect to %s: %s", hostname, e)
            session.send(HEADER_CONNECTPB + str(e).encode('utf-8', errors='replace'))
            session.close()
            raise
        else:
            session.send(HEADER_CONNECTOK)
        return sock
    
    @staticmethod
    def handle(session, sock):
        continuing = True
        tosendtosession = bytearray()
        while continuing:
            # read from socket
            r , _, _ = select([socket],[],[], timeout=0.001)
            sendwhatisstored = False
            if socket in r:
                data = r.read(1024)
                if not data:
                    # connection closed
                    continuing = False
                    sendwhatisstored = True
                else:
                    tosendtosession.extend(data)
                    if tosendtosession + 1024 < session.maxdatalength:
                        sendwhatisstored = True
            else:
                sendwhatisstored = True
            if sendwhatisstored and tosendtosession:
                session.send(HEADER_NORMAL + tosendtosession)
                tosendtosession.clear()
            # read from session
            if session.checkIfDataAvailable():
                data = session.receiveChunk()
                if data is not None:
                    if data:
                        if data.startswith(HEADER_NORMAL):
                            toforward = data[len(HEADER_NORMAL):]
                            sock.send(toforward)
                            sock.flush()
                        elif data.startswith(HEADER_STOP):
                            sock.close()
                            continuing = False
                        else:
                            LOGGER.warning("Unknown message received: %r", data)
                    else:
                        # no data received? Strange
                        pass
                else:
                    sock.close()
                    continuing = False
    
    def mainLoop(self, session):
        sock = self.createSocket(session)
        self.handle(session, sock)

class TcpSocketActionServer(GenericTcpSocketActionServer):
    def __init__(self, hostname, port):
        GenericTcpSocketActionServer.__init__(self, 'socket-%s:%s' % (hostname, port))
        self.hostname = hostname
        self.port = port
    
    def createSocket(self, session):
        '''Creates a socket to what is indicated'''
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(0)
        try:
            sock.connect((self.hostname, self.port))
        except Exception as e:
            LOGGER.warning("Impossible to connect to %s: %s", self.hostname, e)
            session.close()

class LocalhostTcpSocketActionServer(TcpSocketActionServer):
    def __init__(self, port):
        TcpSocketActionServer.__init__(self, 'localhost', port)

'''https://fr.wikipedia.org/wiki/SOCKS'''
# TODO: create socks proxy






def generateSessionFactoryForGenericSocket(simpleSessionFactory, hostname, port):
    session = simpleSessionFactory()
    session.send(b'hostname\nport\n')
    while not session.checkIfDataAvailable() and not session.closed:
        time.sleep(0.1)
    data = session.receiveChunk()
    if not data or not data.startswith(HEADER_CONNECTOK):
        LOGGER.warning("Session closed while connecting.\n%r", data)
        return None
    return session

def createLocalServerForRemoteClient(localport, sessionFactory):
    '''Creates a server on the given port. When a connection is requested, a session is created through the provided factory, then the two live their life together.
    Example session factories:
    client = XxxxCommunicationClient()
    # if TcpSocketActionServer in action
    factory = lambda:client.openSession('socket-hostname:port')
    
    # if GenericTcpSocketActionServer in action
    def factory():
        session = client.openSession('socket')
        session.send(b'hostname\nport\n')
        while not session.checkIfDataAvailable() and not session.closed:
            time.sleep(0.1)
        data = session.receiveChunk()
        if not data:
            return None
        if not data.startswith(
        return session
    '''
    
    


