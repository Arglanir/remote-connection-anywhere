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

CAPA_PREFIX = 'socket'

class GenericTcpSocketActionServer(ActionServer):
    '''ActionServer that connects to the hostname:port provided by the session. May not be that useful, rather use the socks module.'''
    
    def __init__(self, capability=CAPA_PREFIX):
        ActionServer.__init__(self, capability)
    
    def start(self, session):
        ActionServer.start(self, session)
        threading.Thread(target=self.mainLoop, name="tcpthread-%s-%s" % (self.capability, session.sid), args=(session,)).start()
    
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
        '''Make a session and socket communicate using a simple protocol: on the session the messages start with DATA.'''
        LOGGER.info("Session %s is now in loop", session.sid)
        continuing = True
        tosendtosession = bytearray()
        while continuing:
            # read from socket
            r , _, _ = select([sock],[],[], 0.001) #timeout
            sendwhatisstored = False
            if sock in r:
                data = sock.recv(1024)
                if not data:
                    # connection closed
                    continuing = False
                    #LOGGER.debug("Connection closed, sending remaining %s...", len(tosendtosession))
                    sendwhatisstored = True
                else:
                    tosendtosession.extend(data)
                    if len(tosendtosession) + 1024 > session.maxdatalength:
                        #LOGGER.debug("Size already too big: %s, sending...", len(tosendtosession))
                        sendwhatisstored = True
            else:
                #if tosendtosession: LOGGER.debug("No more data in select, sending...")
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
        LOGGER.info("Session %s is terminated", session.sid)
    
    def mainLoop(self, session):
        sock = self.createSocket(session)
        self.handle(session, sock)

class TcpSocketActionServer(GenericTcpSocketActionServer):
    '''ActionServer that connects to a specific hostname:port, specified at startup.'''
    def __init__(self, hostname, port):
        GenericTcpSocketActionServer.__init__(self, '%s-%s:%s' % (CAPA_PREFIX, hostname, port))
        self.hostname = hostname
        self.port = port
    
    def createSocket(self, session):
        '''Creates a socket to what is indicated'''
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #sock.setblocking(0)
        try:
            sock.connect((self.hostname, self.port))
        except Exception as e:
            LOGGER.warning("Impossible to connect to %s: %s", self.hostname, e)
            session.send(HEADER_CONNECTPB + str(e).encode('utf-8', errors='replace'))
            session.close()
            raise
        else:
            session.send(HEADER_CONNECTOK)
        return sock

class LocalhostTcpSocketActionServer(TcpSocketActionServer):
    '''Simple TcpSocketActionServer just for localhost connexion.'''
    def __init__(self, port):
        TcpSocketActionServer.__init__(self, 'localhost', port)

'''https://fr.wikipedia.org/wiki/SOCKS'''
# For a socks proxy, see socks.py






def generateSessionFactoryForGenericSocket(simpleSessionFactory, hostname, port):
    '''Factory for a session connected to a GenericTcpSocketActionServer'''
    def toreturn():
        session = simpleSessionFactory()
        session.send("{}\n{}\n".format(hostname, port).encode('utf-8'))
        while not session.checkIfDataAvailable() and not session.closed:
            time.sleep(0.1)
        data = session.receiveChunk()
        if not data or not data.startswith(HEADER_CONNECTOK):
            LOGGER.warning("Session closed while connecting.\n%r", data)
            return None
        LOGGER.info("Session now ready")
        return session
    return toreturn

def generateSessionFactoryForSpecificSocket(simpleSessionFactory):
    '''Factory for a session connected to a TcpSocketActionServer'''
    def toreturn():
        session = simpleSessionFactory()
        #session.send(b'hostname\nport\n')
        while not session.checkIfDataAvailable() and not session.closed:
            time.sleep(0.1)
        data = session.receiveChunk()
        if not data or not data.startswith(HEADER_CONNECTOK):
            LOGGER.warning("Session closed while connecting.\n%r", data)
            return None
        LOGGER.info("Session now ready")
        return session
    return toreturn

def runLocalServerForRemoteClient(localport, commClient, server_id=None, server_capa=None, hostname=None, distant_port=None):
    '''Creates a server on the given port. When a connection is requested, a session is created through the client, then the two live their life together.
    '''
    
    if server_id is None:
        servers_ids = commClient.listServers()
        if not servers_ids:
            raise ValueError("No default server found.")
        if len(servers_ids) > 1:
            raise ValueError("Missing server_id and impossible to choose between %r" % servers_ids)
        server_id = servers_ids[0]
    
    if server_capa is None:
        capa_sockets = [capa for capa in commClient.capabilities(server_id) if capa.startswith(CAPA_PREFIX)]
        capa_sockets_specific = [capa for capa in capa_sockets if '-' in capa]
        if not capa_sockets:
            raise ValueError("There is no TCP server running on %s: %s" % (server_id, commClient.capabilities(server_id)))
        if hostname is not None and distant_port is not None and CAPA_PREFIX in capa_sockets:
            server_capa = CAPA_PREFIX
        elif hostname is None and distant_port is None and capa_sockets_specific:
            if len(capa_sockets_specific) == 1:
                server_capa = capa_sockets_specific[0]
            else:
                raise ValueError("Impossible to choose between connections on %s: %r" % (server_id, capa_sockets_specific))
        elif '%s-%s:%s' % (CAPA_PREFIX, hostname, distant_port) in capa_sockets_specific:
            server_capa = '%s-%s:%s' % (CAPA_PREFIX, hostname, distant_port)
        elif hostname is not None and distant_port is not None and CAPA_PREFIX not in capa_sockets:
            raise ValueError("Impossible to generically connect to %s:%s through %s: %r" % (hostname, distant_port, server_id, capa_sockets_specific))
        else:
            raise ValueError("Impossible to choose between connections on %s: %r" % (server_id, capa_sockets_specific))
    
    if '-' in server_capa: # hostname/port already known
        sessionFactory = generateSessionFactoryForSpecificSocket(lambda: commClient.openSession(server_id, server_capa))
    else: # hopefully with checks above hostname is not None and distant_port is not None
        # generic
        sessionFactory = generateSessionFactoryForGenericSocket(lambda: commClient.openSession(server_id, server_capa), hostname, distant_port)
    
    localServer = socket.create_server(('', localport))
    LOGGER.info("TCP server listening on %s for %s/%s", localport, server_id, server_capa)
    while True:
        newSocket, address = localServer.accept()
        LOGGER.info("New connection from %s", address)
        session = sessionFactory()
        thread = threading.Thread(target=GenericTcpSocketActionServer.handle, name="Client-to-%s:%s:%s" % (server_capa, hostname, distant_port), args=(session, newSocket))
        thread.start()

    


'''
example: 

server:

import logging; logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s [%(threadName)s] %(module)s.%(funcName)s %(message)s',
    handlers=[logging.FileHandler("debug.log",mode="w"), logging.StreamHandler()])
# start http server somewhere using python3 -m http.server 8001

folder = 'toto'
from remoteconanywhere.folder import FolderCommServer
from remoteconanywhere.socket import LocalhostTcpSocketActionServer
import socket
server = FolderCommServer("serverOn" + socket.gethostname().replace('-', ''), folder)
server.cleanUp()
server.registerCapability(LocalhostTcpSocketActionServer(8001))
server.serveForever()

client:

import logging; logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s [%(threadName)s] %(module)s.%(funcName)s %(message)s',
    handlers=[logging.FileHandler("debug.log",mode="w"), logging.StreamHandler()])
folder = 'toto'
from remoteconanywhere.folder import FolderCommClient
import socket
from remoteconanywhere.socket import runLocalServerForRemoteClient
client = FolderCommClient("clientOn" + socket.gethostname().replace('-', ''), folder)
runLocalServerForRemoteClient(8002, client)

'''