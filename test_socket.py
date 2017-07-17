'''
This script shows how to create socket proxies in python.

Created on 17 Jul 2017

@author: Cedric Mayer
'''

import socket
import select
import threading
import sys
import asyncio
from cmath import asin

BUFFERSIZE = 8192

########################## Thread-based proxy

def handleOneConnection(clientsock, distantsock):
    """Handler for one connection, that runs in a thread.
    It copies everything from one socket to the other.
    @param clientsock: A client socket
    @param distantsock: Another socket"""
    try:
        # counter of transmitted data
        transmitted1, transmitted2 = 0, 0
        while True:
            # wait for data
            rready, _, errors = select.select((clientsock, distantsock), (), (clientsock, distantsock))
            if errors:
                break
            for ready in rready:
                # read data
                data = ready.recv(BUFFERSIZE)
                if not data:
                    return
                # select destination
                if ready is distantsock:
                    out = clientsock
                    transmitted1 += len(data)
                else:
                    out = distantsock
                    transmitted2 += len(data)
                # send data
                out.sendall(data)
    except BrokenPipeError:
        # end of communication
        pass
    except KeyboardInterrupt:
        # end of server
        pass
    finally:
        clientsock.close()
        distantsock.close()
        print("Connection terminated. Transmitted: %s/%s" % (transmitted1, transmitted2))

def testSocketThreads(port, distanthost, distantport):
    """Creates a proxy on given port, to the distanthost and distantport.
    Each connection in run in a specific thread.
    @param port: The local port to listen on.
    @param distanthost: The distant host
    @param distantport: The distant port"""
    sock = socket.socket()
    sock.bind(('', port))
    sock.listen(5)
    print("Server started on port", port)
    while 1:
        try:
            clientsock, clientaddress = sock.accept()
        except KeyboardInterrupt:
            break
        print("Accepting new connection from", clientaddress)
        distantsock = socket.socket()
        distantsock.connect((distanthost, distantport))
        t = threading.Thread(target=handleOneConnection, args=(clientsock,distantsock))
        t.name = "ThreadFor{}".format(clientaddress)
        t.start()
    print('End of server')
    sock.close()

#########################" Asyncio-based proxy

@asyncio.coroutine
def transmitData(from_reader, to_writer):
    """This coroutine writes everything from the reader to the writer.
    @param from_reader: Reader to read from
    @param to_writer: Writer to send read data to
    @return: The number of bytes sent."""
    totaltransmitted = 0
    try:
        while True:
            data = yield from from_reader.read(BUFFERSIZE)
            if not data:
                break
            totaltransmitted += len(data)
            to_writer.write(data)
            yield from to_writer.drain()
    except KeyboardInterrupt:
        pass
    except ConnectionResetError:
        pass
    finally:
        to_writer.close()
    return totaltransmitted

def createHandlerClientConnected(loop, distanthost, distantport):
    """This method creates the handler for one connection."""
    @asyncio.coroutine
    def handleClientConnected(client_reader, client_writer):
        """The coroutine that will take care of one connection."""
        loop.TOTAL_CONNECTIONS += 1
        addr = client_writer.get_extra_info('peername')
        print("Connected to", addr, "(%s pending connections)" % loop.TOTAL_CONNECTIONS)
        distantreader, distantwriter = yield from asyncio.open_connection(distanthost, distantport, loop=loop)
        t1 = loop.create_task(transmitData(distantreader, client_writer))
        t2 = loop.create_task(transmitData(client_reader, distantwriter))
        transmitted1, transmitted2 = yield from asyncio.gather(t1, t2)
        loop.TOTAL_CONNECTIONS -= 1
        print("End of communication to", addr, "(%s pending connections)" % loop.TOTAL_CONNECTIONS, "(Transmitted: %s/%s)" % (transmitted1, transmitted2))
    
    return handleClientConnected

def testSocketAsyncio(port, distanthost, distantport):
    """Creates a proxy on given port, to the distanthost and distantport.
    Everything run in one event loop in the same current thread.
    @param port: The local port to listen on.
    @param distanthost: The distant host
    @param distantport: The distant port"""
    loop = asyncio.get_event_loop()
    loop.TOTAL_CONNECTIONS = 0
    coro = asyncio.start_server(createHandlerClientConnected(loop, distanthost, distantport), port=port, loop=loop)
    server = loop.run_until_complete(coro)
    print('Serving on {}'.format(server.sockets[0].getsockname()))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    print('End of server')
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()
    


if __name__ == '__main__':
    if len(sys.argv) != 5 or "testSocket"+sys.argv[1].title() not in globals():
        print("Usage:", sys.argv[0], "[threads|asyncio] [localport] [distanthost] [distantport]")
        sys.exit(1)
    method = globals()["testSocket"+sys.argv[1].title()]
    method(int(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
