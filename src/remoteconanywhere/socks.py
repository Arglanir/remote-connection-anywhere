'''
This implements a SOCKS proxy on localhost that connect to a back-end on another network

Created on 17 avr. 2020

@author: Cedric
'''

from remoteconanywhere.communication import ActionServer
import threading
import time
import socket
from select import select
import logging
import os
from collections import defaultdict
import struct
import ctypes
import chunk

LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))


class SocksFrontEnd():
    '''Implementation of a socks4 proxy, client side'''
    CAPA = 'socks'
    HEADER_DATA = b'DATA'
    
    LOOP_TIMEOUT = 0.01
    DATA_TIMEOUT = 0.02
    BLOCK_SIZE = 1024
    def __init__(self, client, localport, rid):
        self.client = client
        self.sockServer = None
        self.port = localport
        self.rid = rid
        self.session2connexion = {}
        self.stopped = False
    
    def stop(self):
        self.stopped = True
        
    def start(self):
        self.stopped = False
        threading.Thread(target=self.run, name="%s-%s-sockets2sessions" % (self.__class__.__name__, self.port)).start()
        threading.Thread(target=self.runSessionDataToSocket, name="%s-%s-sessions2sockets" % (self.__class__.__name__, self.port)).start()
    
    def runSessionDataToSocket(self):
        while not self.stopped:
            time.sleep(self.LOOP_TIMEOUT)
            for s, c in list(self.session2connexion.items()):
                # if session is closed, it should not be here anymore
                while s.checkIfDataAvailable():
                    chunk = s.receiveChunk()
                    if chunk:
                        if chunk.startswith(self.HEADER_DATA) and len(chunk) > len(self.HEADER_DATA):
                            # transmit data to connection
                            try:
                                tosend = chunk[len(self.HEADER_DATA):]
                                LOGGER.debug("Sending to socket some data from sid=%s: %s", s.sid, tosend)
                                c.sendall(tosend)
                            except:
                                s.close()
                                c.close()
                        else:
                            LOGGER.warn("Unable to process message %s", chunk)
                
            
    def run(self):
        self.sockServer = sockServer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sockServer.setblocking(False)
        LOGGER.info("Server SOCKS frontend started on port %s", self.port)
        sockServer.bind(('localhost', self.port))
        sockServer.listen(128)
        inputs = [sockServer]
        outputs = []
        connexion2session = {}
        dataToSendByconnex = {}
        dataSentByConnex = defaultdict(int)
        lastDateSentByConnex = {}
        def endOfComm(c, notifySession=False):
            inputs.remove(c)
            if c in outputs:
                outputs.remove(c)
            try:
                session = connexion2session[c]
                session.close(notifySession)
                del connexion2session[c]
                del self.session2connexion[session]
            except KeyError:
                pass
            lastDateSentByConnex.pop(c, None)
            dataToSendByconnex.pop(c, None)
            c.close()
        def forceSend(b, c, session=None):
            if session is None:
                session = connexion2session[c]
            session.send(self.HEADER_DATA + b)
            dataSentByConnex[c] += len(b)
            b.clear()
            lastDateSentByConnex[c] = time.time()
        while inputs:
            readable, _writable, exceptional = select(
                inputs, outputs, inputs, self.LOOP_TIMEOUT)
            for c in readable:
                if c is sockServer:
                    # new connection
                    connection, client_address = c.accept()
                    LOGGER.info("New socket from %s", client_address)
                    connection.setblocking(0)
                    inputs.append(connection)
                    session = connexion2session[connection] = self.client.openSession(self.rid, self.CAPA)
                    dataToSendByconnex[connection] = bytearray()
                    self.session2connexion[session] = connection
                else:
                    data = c.recv(self.BLOCK_SIZE)
                    if data:
                        # send data to other end
                        session = connexion2session[c]
                        b = dataToSendByconnex[c]
                        b.extend(data)
                        LOGGER.debug("Current data to send: %r", "size %s" % len(b) if len(b) > 50 else b)
                        if (len(b) + self.BLOCK_SIZE > session.maxdatalength or
                            (dataSentByConnex[c] == 0 and len(b) >=9 # first message: header must be complete
                             and ((b[4:7] != b'\x00\x00\x00' and 0 in b[8:]) # socks 4 header
                                  or (b[4:7] == b'\x00\x00\x00' and b[7] != 0 and b[8:].count(0) >= 2)))): # socks 4a header
                            # send first frame with connection information
                            forceSend(b, c, session)
                    else:
                        # end of connection from here
                        endOfComm(c)
            for c in exceptional:
                endOfComm(c)
            for c in lastDateSentByConnex:
                now = time.time()
                if dataToSendByconnex[c] and now - lastDateSentByConnex[c] > self.DATA_TIMEOUT:
                    b = dataToSendByconnex[c]
                    forceSend(b, c)
            if self.stopped:
                break
        # end of loop: stop all sockets & sessions
        for c in list(inputs):
            endOfComm(c, True)

def transmitDataBetween(session, connection, info=None, rest=None):
    tosend = bytearray()
    if rest:
        LOGGER.debug("Sending immediately some data left after socks identification to %s: %r", info, rest)
        connection.sendall(rest)
    LOGGER.info("Starting to transmit data to/from sid=%s to %s", session.sid, info)
    while not session.closed:
        r, _, x = select([connection], [], [connection], SocksFrontEnd.LOOP_TIMEOUT)
        if x:
            break
        if r:
            if connection.fileno() < 0:
                # otherwise bug in windows
                LOGGER.info("Connection closed as fileno = %s", connection.fileno())
                break
            LOGGER.debug("Ready to read connection %s", connection)
            data = connection.recv(SocksFrontEnd.BLOCK_SIZE)
            if not data:
                break
            LOGGER.debug("Receiving something on socket %s: %r", info, data)
            tosend.extend(data)
            if len(tosend) + SocksFrontEnd.BLOCK_SIZE > session.maxdatalength:
                LOGGER.debug("Sending back %r to session  %s", data, info)
                session.send(SocksFrontEnd.HEADER_DATA + tosend)
                tosend.clear()
        else:
            if tosend:
                LOGGER.debug("Sending back %r to session %s as no more data", tosend, info)
                session.send(SocksFrontEnd.HEADER_DATA + tosend)
                tosend.clear()
        while session.checkIfDataAvailable():
            data = session.receiveChunk()
            if data is None:
                # end of communication
                break
            LOGGER.debug("Receiving something on session %s: %r, sending it immediately", info, data)
            if data.startswith(SocksFrontEnd.HEADER_DATA):
                try:
                    connection.sendall(data[len(SocksFrontEnd.HEADER_DATA):])
                except:
                    LOGGER.warning("Error while sending data:", exc_info=1)
                    break
    LOGGER.info("End of communication between sid=%s and %s", session.sid, info)
    if tosend:
        LOGGER.debug("Sending back %r to session %s when closing connection", data, info)
        session.send(SocksFrontEnd.HEADER_DATA + tosend)
        tosend.clear()
    connection.close()
    if not session.closed:
        session.close()

# https://www.openssh.com/txt/socks4.protocol
# https://www.openssh.com/txt/socks4a.protocol
SOCKS4_CLIENT_HEADER = struct.Struct("!BBHI")

class Socks4ClientHeader(ctypes.BigEndianStructure):
    _fields_ = [("version", ctypes.c_byte, 8),
                 ("command", ctypes.c_byte, 8),
                 ("dstport", ctypes.c_uint16, 16),
                 ("dstip", ctypes.c_uint32, 32)]

class SocksError(Exception):
    def __init__(self, errno):
        self.errno = errno

CONNECT = 1
BIND = 2


def findFreePort():
    """
    Return a free port
    @param start: starting port
    @param end: end port
    @return: A free port wher you can bind
    """
    try:
        sock = socket.socket()
        sock.bind(('', 0))
        # in order to reuse it right away
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.getsockname()[1]
    finally:
        sock.close()

class Socks4Backend(ActionServer):
    '''Implementation of a socks4 proxy'''
    def __init__(self, capability='socks'):
        super().__init__(capability)
    
    def start(self, session):
        '''Given a session, able to communicate / start the application'''
        # first chunk is a message
        LOGGER.info("Starting session %s with %s", session.sid, session.other)
        while not session.checkIfDataAvailable():
            time.sleep(SocksFrontEnd.LOOP_TIMEOUT)
        chunk = session.receiveChunk()
        LOGGER.debug("Received data to open session: %s", chunk)
        if chunk.startswith(SocksFrontEnd.HEADER_DATA):
            chunk = chunk[len(SocksFrontEnd.HEADER_DATA):]
        try:
            if len(chunk) < ctypes.sizeof(Socks4ClientHeader):
                raise SocksError(91)
            headerb = chunk[:ctypes.sizeof(Socks4ClientHeader)]
            header = Socks4ClientHeader.from_buffer_copy(headerb)
            if header.version != 4:
                raise SocksError(91)
            connectto = header.dstip
            rest = chunk[ctypes.sizeof(Socks4ClientHeader):]
            first0 = rest.index(0)
            _identification = rest[:first0]
            rest = rest[first0 + 1:]
            if 0 < header.dstip < 256: # socks 4a header 
                second0 = rest.index(0)
                # name is given after the id
                domainname = rest[:second0]
                connectto = domainname.decode('utf-8') # TODO: check supposed encoding
                rest = rest[second0 + 1:]
                LOGGER.debug("Received Socks4a header, to connect to %s", connectto)
            else:
                connectto = socket.inet_ntoa(struct.pack("!I", connectto))
                LOGGER.debug("Received Socks4 header, to connect to %s", connectto)
            if header.command == CONNECT:
                # initialize connection
                c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    LOGGER.info("Creating a new connection to %s", (connectto, header.dstport))
                    c.connect((connectto, header.dstport))
                    c.setblocking(False)
                except (ConnectionRefusedError, TimeoutError):
                    raise SocksError(92)
                toreturn = Socks4ClientHeader()
                toreturn.version = 0
                toreturn.command = 90
                session.send(SocksFrontEnd.HEADER_DATA + ctypes.string_at(ctypes.addressof(toreturn), ctypes.sizeof(toreturn)))
                threading.Thread(target=transmitDataBetween, args=(session, c, "%s:%s" % (connectto, header.dstport)),
                                 kwargs=dict(rest=rest),
                                 name='connection-from-%s-to-%s:%s' % (session.sid, connectto, header.dstport)).start()
            elif header.command == BIND:
                # initialize server
                c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                c.bind()
            else:
                raise SocksError(91)
        except SocksError as se:
            LOGGER.warn("Problem when initializing a new connection:", exc_info=1)
            toreturn = Socks4ClientHeader()
            toreturn.version = 0
            toreturn.command = se.errno
            session.send(SocksFrontEnd.HEADER_DATA + ctypes.string_at(ctypes.addressof(toreturn), ctypes.sizeof(toreturn)))
            session.close()
        except Exception:
            LOGGER.warn("Problem when initializing a new connection:", exc_info=1)
            toreturn = Socks4ClientHeader()
            toreturn.version = 0
            toreturn.command = 91
            session.send(SocksFrontEnd.HEADER_DATA + ctypes.string_at(ctypes.addressof(toreturn), ctypes.sizeof(toreturn)))
            session.close()
        
    
