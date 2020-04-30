'''
This implements a SOCKS proxy on localhost that connect to a back-end on another network

# https://www.openssh.com/txt/socks4.protocol
# https://www.openssh.com/txt/socks4a.protocol

# https://tools.ietf.org/html/rfc1928

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

LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))


class Socks4FrontEnd():
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
                # if session is closed, it should not be here anymore... maybe a little
                if s.closed:
                    continue
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
                            LOGGER.warning("Unable to process message %s", chunk)
                    # closing connection from other point
                        
    
    def newSession(self):
        session = self.client.openSession(self.rid, self.CAPA)
        return session
    
    def finishSession(self, session):
        pass
            
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
                self.finishSession(session)
            except KeyError:
                pass
            lastDateSentByConnex.pop(c, None)
            dataToSendByconnex.pop(c, None)
            c.close()
        def forceSend(b, c, session=None, sendOnly=0):
            if session is None:
                session = connexion2session[c]
            tosend = b
            if sendOnly:
                tosend = b[:sendOnly]
            session.send(self.HEADER_DATA + tosend)
            dataSentByConnex[c] += len(tosend)
            b[:len(tosend)] = []
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
                    session = connexion2session[connection] = self.newSession()
                    LOGGER.info("New session %s created for %s", session.sid, client_address)
                    dataToSendByconnex[connection] = bytearray()
                    self.session2connexion[session] = connection
                else:
                    data = None
                    try:
                        data = c.recv(self.BLOCK_SIZE)
                    except:
                        LOGGER.warn("Problem while receiving: (will close the connection)", exc_info=True)
                    if data:
                        # send data to other end
                        session = connexion2session[c]
                        b = dataToSendByconnex[c]
                        b.extend(data)
                        LOGGER.debug("Current data to send: %r", "size %s" % len(b) if len(b) > 50 else b)
                        self.analyseAndSend(dataSentByConnex, c, b, session, forceSend, False)
                    else:
                        # end of connection from here
                        endOfComm(c)
            for c in exceptional:
                endOfComm(c)
            for c in lastDateSentByConnex:
                now = time.time()
                if dataToSendByconnex[c] and now - lastDateSentByConnex[c] > self.DATA_TIMEOUT:
                    b = dataToSendByconnex[c]
                    session = connexion2session[c]
                    self.analyseAndSend(dataSentByConnex, c, b, session, forceSend, True)
                    #forceSend(b, c)
            for s, c in list(self.session2connexion.items()):
                # cleaning closed sessions
                if session.closed:
                    endOfComm(c)
            if self.stopped:
                break
        # end of loop: stop all sockets & sessions
        for c in list(inputs):
            endOfComm(c, True)
    
    def analyseAndSend(self, dataSentByConnex, connection, binarydata, session, forceSend, noMoreReceivedData):
        sendiffirstconnection = False
        if dataSentByConnex[connection] == 0:
            # first message, analyse what to send
            status, reason = analyseSocks4Header(binarydata)
            if status != COMPLETE:
                LOGGER.debug("Header %s in status %s because %s", binarydata, status, reason)
            if status == COMPLETE or status == INVALID:
                sendiffirstconnection = True
        if len(binarydata) + self.BLOCK_SIZE > session.maxdatalength or noMoreReceivedData or sendiffirstconnection:
            # send first frame with connection information
            forceSend(binarydata, connection, session)

SocksFrontEnd = Socks4FrontEnd

class Socks5FrontEnd(Socks4FrontEnd):
    CAPA = "socks5"
    
    def __init__(self, client, localport, rid):
        Socks4FrontEnd.__init__(self, client, localport, rid)
        self.currentNegotiationBySession = dict() # session => 0 start, 1 identification 10 last header
    
    def newSession(self):
        session = Socks4FrontEnd.newSession(self)
        self.currentNegotiationBySession[session] = 0
        return session
    
    def finishSession(self, session):
        Socks4FrontEnd.finishSession(self, session)
        del self.currentNegotiationBySession[session]
    
    def analyseAndSend(self, dataSentByConnex, connection, binarydata, session, forceSend, noMoreReceivedData):
        sendiffirstconnection = False
        LOGGER.debug("Analysing data to send after %s bytes", dataSentByConnex[connection])
        ntosend = len(binarydata)
        if self.currentNegotiationBySession[session] == 0:
            # first message, analyse what to send
            status, ntosend, reason = analyseSocks5Header(binarydata, 0)
            if status != COMPLETE:
                LOGGER.debug("Header %s in status %s because %s", binarydata, status, reason)
            if status == COMPLETE or status == INVALID:
                sendiffirstconnection = True
                self.currentNegotiationBySession[session] += 1
            if status == COMPLETE:
                if 0 in binarydata[2:2+binarydata[1]]:
                    # no identification possible, great! This will be chosen
                    self.currentNegotiationBySession[session] = 10
                elif 2 in binarydata[2:2+binarydata[1]]:
                    # user/password: 1 more message
                    self.currentNegotiationBySession[session] = 9
        elif self.currentNegotiationBySession[session] < 10:
            # TODO: how to handle this? Maybe only one message?
            sendiffirstconnection = True
            self.currentNegotiationBySession[session] += 1
        elif self.currentNegotiationBySession[session] == 10:
            # second header, analyse it
            status, ntosend, reason = analyseSocks5Header(binarydata, 1)
            if status != COMPLETE:
                LOGGER.debug("Header %s in status %s because %s", binarydata, status, reason)
            if status == COMPLETE or status == INVALID:
                sendiffirstconnection = True
                # no header anymore
                self.currentNegotiationBySession[session] += 1
        if len(binarydata) + self.BLOCK_SIZE > session.maxdatalength or sendiffirstconnection or noMoreReceivedData:
            # send first frame with connection information
            LOGGER.debug("Current negotiation before sending: %s", self.currentNegotiationBySession[session])
            forceSend(binarydata, connection, session, sendOnly=ntosend)

def transmitDataBetween(session, connection, info=None, rest=None):
    tosend = bytearray()
    if rest:
        LOGGER.debug("Sending immediately some data left after socks identification to %s: %r", info, rest)
        connection.sendall(rest)
    LOGGER.info("Starting to transmit data to/from sid=%s to %s", session.sid, info)
    while not session.closed:
        r, _, x = select([connection], [], [connection], Socks4FrontEnd.LOOP_TIMEOUT)
        if x:
            break
        if r:
            if connection.fileno() < 0:
                # otherwise bug in windows
                LOGGER.info("Connection closed as fileno = %s", connection.fileno())
                break
            LOGGER.debug("Ready to read connection %s", connection)
            data = connection.recv(Socks4FrontEnd.BLOCK_SIZE)
            if not data:
                break
            LOGGER.debug("Receiving something on socket %s: %r", info, data)
            tosend.extend(data)
            if len(tosend) + Socks4FrontEnd.BLOCK_SIZE > session.maxdatalength:
                LOGGER.debug("Sending back %r to session  %s", data, info)
                session.send(Socks4FrontEnd.HEADER_DATA + tosend)
                tosend.clear()
        else:
            if tosend:
                LOGGER.debug("Sending back %r to session %s as no more data", tosend, info)
                session.send(Socks4FrontEnd.HEADER_DATA + tosend)
                tosend.clear()
        while session.checkIfDataAvailable():
            data = session.receiveChunk()
            if data is None:
                # end of communication
                break
            LOGGER.debug("Receiving something on session %s: %r, sending it immediately", info, data)
            if data.startswith(Socks4FrontEnd.HEADER_DATA):
                try:
                    connection.sendall(data[len(Socks4FrontEnd.HEADER_DATA):])
                except:
                    LOGGER.warning("Error while sending data:", exc_info=1)
                    break
    LOGGER.info("End of communication between sid=%s and %s", session.sid, info)
    if tosend:
        LOGGER.debug("Sending back %r to session %s when closing connection", data, info)
        session.send(Socks4FrontEnd.HEADER_DATA + tosend)
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

class Socks5ClientHeader1(ctypes.BigEndianStructure):
    _fields_ = [("version", ctypes.c_byte, 8),
                 ("nmethods", ctypes.c_byte, 8)]


class Socks5ClientHeader2a(ctypes.BigEndianStructure):
    _fields_ = [("version", ctypes.c_byte, 8),
                 ("command", ctypes.c_byte, 8),
                 ("reserved", ctypes.c_byte, 8),
                 ("atyp", ctypes.c_byte, 8),]
class Socks5ClientHeader2c(ctypes.BigEndianStructure):
    _fields_ = [("dstport", ctypes.c_uint16, 16),]

class SocksError(Exception):
    def __init__(self, errno):
        self.errno = errno
    SOCKS4_GRANTED = 90
    SOCKS4_REJECTED = 91
    SOCKS4_CONNECT_FAILED = 92
    SOCKS4_BAD_ID = 93
    
    SOCKS5_SUCCESS = 0x00
    SOCKS5_FAILURE = 0x01
    SOCKS5_CONNECTION_NOT_ALLOWED = 0x02
    SOCKS5_BAD_NETWORK = 0x03
    SOCKS5_UNREACHABLE_HOST = 0x04
    SOCKS5_CONNECTION_REFUSED = 0x05
    SOCKS5_TTL_EXPIRED = 0x06
    SOCKS5_BAD_COMMAND = 0x07
    SOCKS5_BAD_ATYP = 0x08
    

CONNECT = 1
BIND = 2
UDP_BIND = 3

INCOMPLETE = "incomplete"
COMPLETE = "complete"
INVALID = "invalid"

def analyseSocks4Header(data):
    """Analyses the header.
    @param data: The data
    @return "complete", locals() if header is complete, 
            "incomplete", "reason" if header is incomplete,
            "invalid", "reason" if header is invalid."""
    if not data:
        return INCOMPLETE, None
    
    if data[0] == 4:
        if len(data) < ctypes.sizeof(Socks4ClientHeader):
            return INCOMPLETE, "Header of size {} < {}".format(len(data), ctypes.sizeof(Socks4ClientHeader))
        headerb = data[:ctypes.sizeof(Socks4ClientHeader)]
        header = Socks4ClientHeader.from_buffer_copy(headerb)
        connectto = header.dstip
        rest = data[ctypes.sizeof(Socks4ClientHeader):]
        try:
            first0 = rest.index(0)
        except ValueError:
            return INCOMPLETE, "No identification yet"
        _identification = rest[:first0]
        rest = rest[first0 + 1:]
        if 0 < header.dstip < 256: # socks 4a header
            try:
                second0 = rest.index(0)
            except ValueError:
                return INCOMPLETE, "No hostname yet"
            # name is given after the id
            domainname = rest[:second0]
            connectto = domainname.decode('utf-8') # TODO: check supposed encoding
            rest = rest[second0 + 1:]
            LOGGER.debug("Received Socks4a header, to connect to %s", connectto)
        else:
            connectto = socket.inet_ntoa(struct.pack("!I", connectto))
            LOGGER.debug("Received Socks4 header, to connect to %s", connectto)
        return COMPLETE, dict(locals())
    
    return INVALID, "Socks protocol %s not implemented" % data[0]
        

def analyseSocks5Header(data, step=0):
    """Analyses the header.
    @param data: The data
    @param step: The step in the protocol handshake
    @return "complete", consummd, locals() if header is complete, 
            "incomplete", minimum, "reason" if header is incomplete,
            "invalid", sockserror, "reason" if header is invalid."""
    if not data:
        return INCOMPLETE, 1, None
    
    if data[0] == 5:
        if step == 0:
            SIZE1 = ctypes.sizeof(Socks5ClientHeader1)
            if len(data) < SIZE1:
                return (INCOMPLETE, SIZE1, 
                    "Header {} of size {} < {}".format(step+1, len(data), SIZE1))
            headerbytes = data[:ctypes.sizeof(Socks5ClientHeader1)]
            header = Socks5ClientHeader1.from_buffer_copy(headerbytes)
            nmethods = header.nmethods
            if len(data) < SIZE1 + nmethods:
                return (INCOMPLETE, SIZE1 + nmethods, 
                    "Header {} of size {} < {}".format(step+1, len(data), SIZE1 + nmethods))
            methods = data[SIZE1:SIZE1+nmethods]
            consumed = SIZE1 + nmethods
            return COMPLETE, consumed, locals()
        if step == 1:
            SIZE2A = ctypes.sizeof(Socks5ClientHeader2a)
            SIZE2C = ctypes.sizeof(Socks5ClientHeader2c)
            if len(data) < SIZE2A + SIZE2C:
                return (INCOMPLETE, SIZE2A + SIZE2C,
                        "Header {} of size {} < {}".format(step+1, len(data), SIZE2A))
            headerbytes = data[:SIZE2A]
            headera = Socks5ClientHeader2a.from_buffer_copy(headerbytes)
            nextheader = data[SIZE2A:]
            for typ, size, iptype in [(1, 4, "IPv4"), (4, 16, "IPv6")]:
                if headera.atyp == typ: # IPV4
                    if len(nextheader) < SIZE2C + size:
                        return (INCOMPLETE, SIZE2C + SIZE2A + size, "Header {} of size {} < {}".format(iptype, len(data), 10))
                    address = nextheader[:size]
                    portbytes = Socks5ClientHeader2c.from_buffer_copy(nextheader[size:size+SIZE2C])
                    port = portbytes.dstport
                    rest = nextheader[size+SIZE2C:]
                    return COMPLETE, SIZE2C + SIZE2A + size, locals()
            if headera.atyp == 3:
                # full address name
                if len(nextheader) < 2 + SIZE2C:
                    return (INCOMPLETE, SIZE2A + 2 + SIZE2C, "Header {} of size {} < {}".format(iptype, len(data), 10))
                naddress = nextheader[0]
                if len(nextheader) < 1 + naddress + SIZE2C:
                    return (INCOMPLETE, SIZE2A + 1 + naddress + SIZE2C, "Header {} of size {} < {}".format(iptype, len(data), 10))
                address = nextheader[1:1+naddress]
                portbytes = Socks5ClientHeader2c.from_buffer_copy(nextheader[1+naddress:1+naddress+SIZE2C])
                port = portbytes.dstport
                rest = nextheader[1+naddress+SIZE2C:]
                return COMPLETE, SIZE2A + 1 + naddress + SIZE2C, locals()
            return INVALID, SocksError.SOCKS5_BAD_ATYP, "Unknown address type %s" % headera.atyp
        return INVALID, SocksError.SOCKS5_FAILURE, "Unknown step %s" % step
    
    if step > 1:
        return COMPLETE, len(data), dict() # send me, no need of further header
    
    return INVALID, SocksError.SOCKS5_BAD_ATYP, "Socks protocol %s not implemented" % data[0]
        

def findFreePort():
    """
    Return a free port
    @return: A free port where you can bind
    """
    try:
        sock = socket.socket()
        # 0 for the port : the system will choose it for you 
        sock.bind(('', 0))
        # in order to reuse it right away
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # return the port
        return sock.getsockname()[1]
    finally:
        sock.close()

class Socks4Backend(ActionServer):
    '''Implementation of a socks4 proxy'''
    def __init__(self, capability=Socks4FrontEnd.CAPA):
        super().__init__(capability)

    def start(self, session):
        threading.Thread(target=self.startHelper, args=(session,), name="Starting-session-%s-with-%s" % (session.sid, session.other)).start()
    
    def startHelper(self, session):
        '''Given a session, able to communicate / start the application'''
        # first chunk is a message
        LOGGER.info("Starting session %s with %s", session.sid, session.other)
        while not session.checkIfDataAvailable():
            time.sleep(Socks4FrontEnd.LOOP_TIMEOUT)
        chunk = session.receiveChunk()
        LOGGER.debug("Received data to open session: %s", chunk)
        if not chunk:
            LOGGER.info("Session probably already closed.")
            return
        if chunk.startswith(Socks4FrontEnd.HEADER_DATA):
            chunk = chunk[len(Socks4FrontEnd.HEADER_DATA):]
        try:
            status, reason = analyseSocks4Header(chunk)
            if status == INCOMPLETE:
                LOGGER.warning("Incomplete header %s: %s", chunk, reason)
                raise SocksError(91)
            if status == INVALID:
                LOGGER.warning("Invalid header %s: %s", chunk, reason)
                raise SocksError(91)
            header = reason['header']
            connectto = reason['connectto']
            rest = reason['rest']

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
                session.send(Socks4FrontEnd.HEADER_DATA + ctypes.string_at(ctypes.addressof(toreturn), ctypes.sizeof(toreturn)))
                threading.Thread(target=transmitDataBetween, args=(session, c, "%s:%s" % (connectto, header.dstport)),
                                 kwargs=dict(rest=rest),
                                 name='connection-from-%s-to-%s:%s' % (session.sid, connectto, header.dstport)).start()
            elif header.command == BIND:
                # initialize server
                #c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                #c.bind()
                # TODO: implement BIND
                LOGGER.warning("BIND called but not implemented.")
                raise SocksError(92)
            else:
                raise SocksError(91)
        except SocksError as se:
            LOGGER.warning("Problem when initializing a new connection:", exc_info=1)
            toreturn = Socks4ClientHeader()
            toreturn.version = 0
            toreturn.command = se.errno
            session.send(Socks4FrontEnd.HEADER_DATA + ctypes.string_at(ctypes.addressof(toreturn), ctypes.sizeof(toreturn)))
            session.close()
        except Exception:
            LOGGER.warning("Problem when initializing a new connection:", exc_info=1)
            toreturn = Socks4ClientHeader()
            toreturn.version = 0
            toreturn.command = 91
            session.send(Socks4FrontEnd.HEADER_DATA + ctypes.string_at(ctypes.addressof(toreturn), ctypes.sizeof(toreturn)))
            session.close()
        

class Socks5Backend(ActionServer):
    '''Implementation of a socks5 proxy'''
    def __init__(self, capability=Socks5FrontEnd.CAPA):
        super().__init__(capability)
    
    def start(self, session):
        threading.Thread(target=self.startHelper, args=(session,), name="Starting-session-%s-with-%s" % (session.sid, session.other)).start()
    
    def startHelper(self, session):
        '''Given a session, able to communicate / start the application'''
        # first chunk is a message
        LOGGER.info("Starting session %s with %s", session.sid, session.other)
        while not session.checkIfDataAvailable():
            time.sleep(SocksFrontEnd.LOOP_TIMEOUT)
        chunk = session.receiveChunk()
        LOGGER.debug("Received data to open session: %s", chunk)
        if not chunk:
            LOGGER.info("Session probably already closed.")
            return
        if chunk.startswith(SocksFrontEnd.HEADER_DATA):
            chunk = chunk[len(SocksFrontEnd.HEADER_DATA):]
        try:
            status, nstatus, reason = analyseSocks5Header(chunk, 0)
            if status == INCOMPLETE:
                LOGGER.warning("Incomplete header %s: %s", chunk, reason)
                raise SocksError(SocksError.SOCKS5_FAILURE)
            if status == INVALID:
                LOGGER.warning("Invalid header %s: %s", chunk, reason)
                raise SocksError(nstatus)
            methods = reason['methods']
            
            if 0 in methods:
                # no authentication possible, perfect!
                session.send(SocksFrontEnd.HEADER_DATA + b"\x05\x00")
            elif 2 in methods:
                session.send(SocksFrontEnd.HEADER_DATA + b"\x05\x02")
                # TODO: https://tools.ietf.org/html/rfc1929
                pass
            else:
                # no possible authentication, select none and quit
                session.send(SocksFrontEnd.HEADER_DATA + b"\x05\xff")
                session.close()
                return
            
            # waiting for second header
            while not session.checkIfDataAvailable():
                time.sleep(SocksFrontEnd.LOOP_TIMEOUT)
            chunk = session.receiveChunk()
            LOGGER.debug("Received header 2 to open session: %s", chunk)
            if not chunk:
                LOGGER.info("Session probably already closed.")
                return
            if chunk.startswith(SocksFrontEnd.HEADER_DATA):
                chunk = chunk[len(SocksFrontEnd.HEADER_DATA):]
            
            status, nstatus, reason = analyseSocks5Header(chunk, 1)
            
            if status == INCOMPLETE:
                LOGGER.warning("Incomplete header %s: %s", chunk, reason)
                raise SocksError(SocksError.SOCKS5_FAILURE)
            if status == INVALID:
                LOGGER.warning("Invalid header %s: %s", chunk, reason)
                raise SocksError(nstatus)
            
            headera = reason['headera']
            addresstype = headera.atyp
            address = reason['address']
            port = reason['port']
            rest = reason['rest']

            if headera.command == CONNECT:
                # initialize connection
                c = socket.socket(socket.AF_INET6 if addresstype == 4 else socket.AF_INET, socket.SOCK_STREAM)
                
                if addresstype == 1:
                    connectto = socket.inet_ntoa(address)
                elif addresstype == 4:
                    connectto = socket.inet_ntop(socket.AF_INET6, address)
                elif addresstype == 3:
                    connectto = address.decode('utf-8') # TODO: what encoding?
                else:
                    raise SocksError(SocksError.SOCKS5_BAD_ATYP)
                
                try:
                    LOGGER.info("Creating a new connection to %s", (connectto, port))
                    c.connect((connectto, port))
                    c.setblocking(False)
                except (ConnectionRefusedError, TimeoutError):
                    raise SocksError(SocksError.SOCKS5_BAD_NETWORK)
                toreturn = bytearray(chunk)
                toreturn[1] = SocksError.SOCKS5_SUCCESS
                session.send(SocksFrontEnd.HEADER_DATA + toreturn)
                threading.Thread(target=transmitDataBetween, args=(session, c, "%s:%s" % (connectto, port)),
                                 kwargs=dict(rest=rest),
                                 name='connection-from-%s-to-%s:%s' % (session.sid, connectto, port)).start()
            elif headera.command == BIND:
                # initialize server
                #c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                #c.bind()
                LOGGER.warning("BIND called but not implemented.")
                # TODO: implementation
                raise SocksError(SocksError.SOCKS5_BAD_COMMAND)
            elif headera.command == UDP_BIND:
                LOGGER.warning("UDP called but not implemented.")
                # TODO: implementation
                raise SocksError(SocksError.SOCKS5_BAD_COMMAND)
            else:
                raise SocksError(SocksError.SOCKS5_BAD_COMMAND)
        except SocksError as se:
            LOGGER.warning("Problem when initializing a new connection:", exc_info=1)
            toreturn = bytearray(chunk) or bytearray([0,0])
            toreturn[1] = se.errno
            session.send(SocksFrontEnd.HEADER_DATA + toreturn)
            session.close()
        except Exception:
            LOGGER.warning("Unexpected Problem when initializing a new connection:", exc_info=1)
            toreturn = bytearray(chunk) or bytearray([0,0])
            toreturn[1] = SocksError.SOCKS5_FAILURE
            session.send(SocksFrontEnd.HEADER_DATA + toreturn)
            session.close()
        
    

