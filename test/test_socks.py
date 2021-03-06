'''
Created on 17 avr. 2020

@author: Cedric
'''
import unittest
from remoteconanywhere.socks import SOCKS4_CLIENT_HEADER, Socks4ClientHeader, findFreePort, transmitDataBetween, SocksFrontEnd, Socks4Backend,\
    analyseSocks5Header, INCOMPLETE, COMPLETE, INVALID, Socks5FrontEnd, Socks5Backend
from remoteconanywhere.communication import QueueCommunicationSession, QueueCommClient, QueueCommServer
from ctypes import sizeof
import socket
import threading
import time
import logging
import select



logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s %(module)s.%(funcName)s [%(threadName)s] %(message)s')


class UpperCaseSocketServer:
    def __init__(self):
        self.port = findFreePort()
        self.running = True
        self.sock = None
    
    def transform(self, data):
        return data.upper()

    def run(self):
        print("Running", self.__class__.__name__, "on port", self.port)
        self.sock = s = socket.socket()
        s.setblocking(False)
        s.bind(('localhost', self.port))
        s.listen(4)
        inputs = [s]
        while self.running:
            r, _w, x = select.select(inputs, [], inputs, 0.01)
            for c in r:
                if c is s:
                    if s.fileno() < 0: break # socket is closed
                    c2, addr = s.accept()
                    print("Accepting a connection from", addr)
                    c2.setblocking(False)
                    inputs.append(c2)
                else:
                    data = c.recv(1024)
                    if not data:
                        inputs.remove(c)
                        c.close()
                        continue
                    toreturn = self.transform(data.decode('UTF-8', errors='ignore'))
                    print("Sending back", toreturn)
                    if toreturn:
                        c.sendall(toreturn.encode('utf-8'))
            for c in x:
                inputs.remove(c)
                c.close()
                continue
        # closing all
        for c in inputs:
            try:
                c.close()
            except:
                pass
        print("Stopping", self.__class__.__name__, "on port", self.port)
    
    def start(self):
        threading.Thread(target=self.run).start()
    
    def stop(self):
        self.running = False
        self.sock.close()

class TestSocks(unittest.TestCase):


    def testStruct(self):
        self.assertEqual(8, SOCKS4_CLIENT_HEADER.size)
        test = SOCKS4_CLIENT_HEADER.unpack(b'\x04\x05\x06\x07\x08\x09\x00\x01')
        self.assertEqual(4, test[0])
        self.assertEqual(5, test[1])
        self.assertEqual(0x607, test[2])
        self.assertEqual(0x8090001, test[3])
        
    def testCtype(self):
        self.assertEqual(8, sizeof(Socks4ClientHeader))
        test = Socks4ClientHeader.from_buffer_copy(b'\x04\x05\x06\x07\x08\x09\x00\x01')
        self.assertEqual(4, test.version)
        self.assertEqual(5, test.command)
        self.assertEqual(0x607, test.dstport)
        self.assertEqual(0x8090001, test.dstip)

    def testFindFreePort(self):
        port = findFreePort()
        s = socket.socket()
        s.bind(('', port))
        s.listen(1)
        print("Found free port", port)
        port2 = findFreePort()
        self.assertNotEqual(port, port2)
        s.close()
        s = socket.socket()
        s.bind(('', port2))
        print("Found free port", port2)
        s.listen(1)
        s.close()
    
    def testAnalyseSock5Header(self):
        def totest(data, step):
            resp = analyseSocks5Header(data, step)
            self.assertEqual(3, len(resp), resp)
            self.assertIn(resp[0], (INCOMPLETE, COMPLETE, INVALID))
            if resp[0] == INCOMPLETE:
                self.assertTrue(resp[1] > len(data), "%s present > %s needed but error ?" % (len(data), resp[1]))
            if resp[0] == COMPLETE:
                self.assertTrue(resp[1] <= len(data), "%s present < %s needed but no error ?" % (len(data), resp[1]))
                if "rest" in resp[2]:
                    self.assertEqual(len(resp[2]["rest"]) + resp[1], len(data), "consumed=%s, rest=%s but data=%s" % (resp[1], resp[2]["rest"], data))
                    self.assertTrue(data.endswith(resp[2]["rest"]))
            return resp
        # test first step
        test = totest(b"", 0)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05", 0)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x06", 0)
        self.assertEqual(INVALID, test[0])
        test = totest(b"\x05\x01", 0)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00", 0)
        self.assertEqual(COMPLETE, test[0])
        
        test = totest(b"", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x06", 1)
        self.assertEqual(INVALID, test[0])
        test = totest(b"\x05\x01\x00", 1)
        self.assertEqual(INCOMPLETE, test[0])
        # ipv4
        test = totest(b"\x05\x01\x00\x01", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x01\xaf\x00\x00\x01", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x01\xaf\x00\x00\x01\x00\xff", 1)
        self.assertEqual(COMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x01\xaf\x00\x00\x01\x00\xffsomedata", 1)
        self.assertEqual(COMPLETE, test[0])
        
        # ipv16
        test = totest(b"\x05\x01\x00\x04", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x04\xaf\x00\x00\x01", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x04\xaf\x00\x00\x01\x00\xff", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x04" + b"\xaf" * 16 + b"\xff", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x04" + b"\xaf" * 16 + b"\x00\xff", 1)
        self.assertEqual(COMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x04" + b"\xaf" * 16 + b"\x00\xffsomedata", 1)
        self.assertEqual(COMPLETE, test[0])
        
        test = totest(b"\x05\x01\x00\x02", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x02\xff\xff", 1)
        self.assertEqual(INVALID, test[0])

        # address string
        test = totest(b"\x05\x01\x00\x03", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x03\x05", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x03\x05hel", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x03\x05hello", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x03\x05hello\x00", 1)
        self.assertEqual(INCOMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x03\x05hello\x00\xff", 1)
        self.assertEqual(COMPLETE, test[0])
        test = totest(b"\x05\x01\x00\x03\x05hello\x00\xffsomedata", 1)
        self.assertEqual(COMPLETE, test[0])
        
    
    def testTransmitData(self):
        session = QueueCommunicationSession()
        try:
            socket1, socket2 = socket.socketpair()
            socket1.setblocking(False)
            socket2.setblocking(False)
            
            socket1.send(b'data')
            time.sleep(0.01)
            self.assertEqual(socket2.recv(10), b'data')
            socket2.send(b'data2')
            time.sleep(0.01)
            self.assertEqual(socket1.recv(10), b'data2')
            
            t = threading.Thread(target=transmitDataBetween, args=(session, socket1, 'info'), name='transmitter')
            t.start()
            tosend = b'Sometest'
            socket2.send(tosend)
            time.sleep(1)
            data = session.memoryGetSentData()
            self.assertEqual(data, b"DATA" + tosend)
            tosend = b'Someothertest'
            session.memoryPutSomeData(b"DATA" + tosend)
            time.sleep(1)
            data = socket2.recv(1024)
            self.assertEqual(data, tosend)
        finally:
            time.sleep(1)
            socket1.close()
            socket2.close()
            session.close()
    
    
    def testSocks4FrontEnd(self):
        try:
            client = QueueCommClient("client-socks")
            portClient = findFreePort()
            frontend = SocksFrontEnd(client, portClient, "test")
            
            frontend.start()
            time.sleep(0.1)
            
            connection = socket.socket()
            print("Connection")
            connection.connect(('localhost', portClient))
            
            headerrequest = SOCKS4_CLIENT_HEADER.pack(4, 1, 255, 0x7F000001)
            
            print("Sending header")
            connection.sendall(headerrequest)
            connection.sendall(b"identification\x00")
            
            time.sleep(0.1)
            sessions = client.sessions["test"]
            self.assertEqual(1, len(sessions))
            # session that asks for a session
            session = sessions[0]
            self.assertIn(b"socks", session.memoryGetSentData()) # indicator
            session.memoryPutSomeData(b"3")
            time.sleep(0.3)
            
            # session opened for communication
            self.assertEqual(2, len(sessions))
            session = sessions[-1]
            
            self.assertEqual(frontend.HEADER_DATA + headerrequest + b"identification\x00", session.memoryGetSentData())
            
            print("sending data")
            session.memoryPutSomeData(frontend.HEADER_DATA + b"hello")
            connection.sendall(b"world!")
            
            time.sleep(0.1)
            
            self.assertEqual(b"hello", connection.recv(5))
            self.assertEqual(frontend.HEADER_DATA + b"world!", session.memoryGetSentData())
            
            time.sleep(0.2)
        finally:
            connection.close()
            frontend.stop()
    
    
    def testSocks5FrontEnd(self):
        try:
            client = QueueCommClient("client-socks")
            portClient = findFreePort()
            frontend = Socks5FrontEnd(client, portClient, "test")
            
            frontend.start()
            time.sleep(0.1)
            
            connection = socket.socket()
            print("Connection")
            connection.connect(('localhost', portClient))
            
            headerrequest = b"\x05\x01\x00"
            headerrequest2 = b"\x05\x01\x00\x03\x08hostname\x00\xff"
            dataafter = b"somedata"
            
            print("Sending header")
            connection.sendall(headerrequest)
            connection.sendall(headerrequest2 + dataafter)
            
            time.sleep(0.1)
            sessions = client.sessions["test"]
            self.assertEqual(1, len(sessions))
            # session that asks for a session
            session = sessions[0]
            self.assertIn(b"socks", session.memoryGetSentData()) # indicator
            session.memoryPutSomeData(b"3")
            time.sleep(0.2)
            
            # session opened for communication
            self.assertEqual(2, len(sessions))
            session = sessions[-1]
            
            self.assertEqual(frontend.HEADER_DATA + headerrequest, session.memoryGetSentData())
            self.assertEqual(frontend.HEADER_DATA + headerrequest2, session.memoryGetSentData())
            self.assertEqual(frontend.HEADER_DATA + dataafter, session.memoryGetSentData())
            
            print("sending data")
            session.memoryPutSomeData(frontend.HEADER_DATA + b"\x05\x00")
            session.memoryPutSomeData(frontend.HEADER_DATA + b"hello")
            connection.sendall(b"world!")
            
            time.sleep(0.1)
            
            self.assertEqual(b"\x05\x00", connection.recv(2))
            self.assertEqual(b"hello", connection.recv(5))
            self.assertEqual(frontend.HEADER_DATA + b"world!", session.memoryGetSentData())
            
            time.sleep(0.2)
        finally:
            connection.close()
            frontend.stop()
    
    def testSocks4BackEndConnect(self):
        
        try:
            otherserver = UpperCaseSocketServer()
            otherserver.start()
            port = otherserver.port
            
            headerrequest = SOCKS4_CLIENT_HEADER.pack(4, 1, port, 0x7F000001) + b'Identification\x00'
            backend = Socks4Backend()
            session = QueueCommunicationSession()
            session.memoryPutSomeData(headerrequest)
            session.memoryPutSomeData(SocksFrontEnd.HEADER_DATA + b'hello world!')
            time.sleep(0.3)
            backend.start(session)
            time.sleep(0.3)
            returned = session.memoryGetSentData()
            self.assertEqual(SocksFrontEnd.HEADER_DATA + b"\x00\x5a\x00\x00\x00\x00\x00\x00", returned)
            returned = session.memoryGetSentData()
            self.assertEqual(SocksFrontEnd.HEADER_DATA + b"HELLO WORLD!", returned)
            session.close()
        finally:
            otherserver.stop()
    
    def testSocks4BackEndSocks4aConnect(self):
        
        try:
            otherserver = UpperCaseSocketServer()
            otherserver.start()
            port = otherserver.port
            
            headerrequest = SOCKS4_CLIENT_HEADER.pack(4, 1, port, 0x00000001) + b'Identification\x00localhost\x00'
            backend = Socks4Backend()
            session = QueueCommunicationSession()
            session.memoryPutSomeData(headerrequest)
            session.memoryPutSomeData(SocksFrontEnd.HEADER_DATA + b'hello world!')
            backend.start(session)
            time.sleep(0.3)
            returned = session.memoryGetSentData()
            self.assertEqual(SocksFrontEnd.HEADER_DATA + b"\x00\x5a\x00\x00\x00\x00\x00\x00", returned, str(returned[5]))
            returned = session.memoryGetSentData()
            self.assertEqual(SocksFrontEnd.HEADER_DATA + b"HELLO WORLD!", returned)
            session.close()
        finally:
            otherserver.stop()
        
    
    def testSocks4BackEndBadConnect(self):
        
        try:
            port = findFreePort()
            # but nothing at the end
            
            headerrequest = SOCKS4_CLIENT_HEADER.pack(4, 1, port, 0x7F000001) + b'Identification\x00'
            backend = Socks4Backend()
            session = QueueCommunicationSession()
            session.memoryPutSomeData(headerrequest)
            backend.start(session)
            time.sleep(0.3)
            returned = session.memoryGetSentData()
            self.assertEqual(SocksFrontEnd.HEADER_DATA + b"\x00\x5c\x00\x00\x00\x00\x00\x00", returned)
            self.assertTrue(session.closed)
        finally:
            #otherserver.stop()
            pass
        
    def testSocks5BackEndConnect(self):
        
        try:
            otherserver = UpperCaseSocketServer()
            otherserver.start()
            port = otherserver.port
            
            backend = Socks5Backend()
            session = QueueCommunicationSession()
            session.memoryPutSomeData(b'\x05\x01\x00')
            session.memoryPutSomeData(b'\x05\x01\x00\x03\x09localhost' + port.to_bytes(2, 'big'))
            session.memoryPutSomeData(SocksFrontEnd.HEADER_DATA + b'hello world!')
            time.sleep(0.1)
            backend.start(session)
            time.sleep(0.3)
            returned = session.memoryGetSentData()
            self.assertEqual(SocksFrontEnd.HEADER_DATA + b"\x05\x00", returned)
            returned = session.memoryGetSentData()
            self.assertEqual(SocksFrontEnd.HEADER_DATA + b"\x05\x00", returned[:len(SocksFrontEnd.HEADER_DATA)+2])
            returned = session.memoryGetSentData()
            self.assertEqual(SocksFrontEnd.HEADER_DATA + b"HELLO WORLD!", returned)
            session.close()
        finally:
            otherserver.stop()

    def testSocks5BackEndBadConnect(self):
        
        try:
            port = findFreePort()
            # but nothing at the end
            
            backend = Socks5Backend()
            session = QueueCommunicationSession()
            session.memoryPutSomeData(b'\x05\x03\x00\x01\x02')
            session.memoryPutSomeData(b'\x05\x01\x00\x03\x09localhost' + port.to_bytes(2, 'big'))
            backend.start(session)
            time.sleep(0.3)
            returned = session.memoryGetSentData()
            self.assertEqual(SocksFrontEnd.HEADER_DATA + b"\x05\x00", returned)
            returned = session.memoryGetSentData()
            self.assertEqual(SocksFrontEnd.HEADER_DATA + b"\x05\x03", returned[:len(SocksFrontEnd.HEADER_DATA)+2])
            self.assertTrue(session.closed)
        finally:
            #otherserver.stop()
            pass
    
    def testSocks4FullProxy(self):
        #return
        try:
            client = QueueCommClient("client-socks")
            server = QueueCommServer("server-socks")
            server.registerCapability(Socks4Backend())
            threading.Thread(target=server.serveForever, name="server").start()
            portClient = findFreePort()
            frontend = SocksFrontEnd(client, portClient, server.rid)
            frontend.start()
            
            time.sleep(1)
            
            print("Start local server")
            portserver = findFreePort()
            myserver = socket.socket()
            myserver.bind(('localhost', portserver))
            myserver.listen(2)
            
            print("Start local client")
            connectionThroughProxy = socket.socket()
            connectionThroughProxy.connect(('localhost', portClient))
            
            
            print("Starting communication")
            headerrequest = SOCKS4_CLIENT_HEADER.pack(4, 1, portserver, 0x7F000001)
            connectionThroughProxy.sendall(headerrequest)
            connectionThroughProxy.sendall(b"identification\x00")
            #time.sleep(0.02) # TODO: remove me soon
            d = b'hello'
            connectionThroughProxy.sendall(d)
            print("Waiting for connection")
            s, _addr = myserver.accept()
            print("Connected, receiving...")
            d2 = s.recv(5)
            self.assertEqual(d, d2)
            
            print("Sending back some data")
            d = b'world!'
            s.sendall(d)
            
            headerresponse = connectionThroughProxy.recv(8)
            print(headerresponse)
            
            d2 = connectionThroughProxy.recv(len(d))
            self.assertEqual(d, d2)
            
            connectionThroughProxy.close()
            
            time.sleep(1)
        
        finally:
            frontend.stop()
            server.stop()
    
    
    def testSocks5FullProxy(self):
        #return
        try:
            client = QueueCommClient("client-socks")
            server = QueueCommServer("server-socks")
            server.registerCapability(Socks5Backend())
            threading.Thread(target=server.serveForever, name="server").start()
            portClient = findFreePort()
            frontend = Socks5FrontEnd(client, portClient, server.rid)
            frontend.start()
            
            time.sleep(1)
            
            print("Start local server")
            portserver = findFreePort()
            myserver = socket.socket()
            myserver.bind(('localhost', portserver))
            myserver.listen(2)
            
            print("Start local client")
            connectionThroughProxy = socket.socket()
            connectionThroughProxy.connect(('localhost', portClient))
            
            
            print("Starting communication")
            connectionThroughProxy.sendall(b"\x05\x01\x00")
            finalsocksheader = b'\x05\x01\x00\x03\x09localhost' + portserver.to_bytes(2, 'big')
            connectionThroughProxy.sendall(finalsocksheader)
            #time.sleep(0.02) # TODO: remove me soon
            d = b'hello'
            connectionThroughProxy.sendall(d)
            print("Waiting for connection")
            s, _addr = myserver.accept()
            print("Connected, receiving...")
            d2 = s.recv(5)
            self.assertEqual(d, d2)
            
            print("Sending back some data")
            d = b'world!'
            s.sendall(d)
            
            # first header socks5
            headerresponse = connectionThroughProxy.recv(2)
            self.assertEquals(b"\x05\x00", headerresponse)
            headerresponse = connectionThroughProxy.recv(len(finalsocksheader))
            self.assertEquals(b"\x05\x00", headerresponse[:2])
            
            d2 = connectionThroughProxy.recv(len(d))
            self.assertEqual(d, d2)
            
            connectionThroughProxy.close()
            
            time.sleep(1)
        
        finally:
            frontend.stop()
            server.stop()

    # TODO: test bind

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testStruct']
    unittest.main()
