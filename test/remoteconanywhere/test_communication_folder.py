'''
Created on 4 avr. 2020

@author: Cedric
'''
import unittest
from remoteconanywhere.communication import *
import os
import threading
import time
import sys

def patch_os_remove():
    temp = os.remove
    def new_remove(*args, **kwargs):
        print("Removing", *args)
        temp(*args, **kwargs)
    os.remove = new_remove
patch_os_remove()

import logging
logging.basicConfig(level='DEBUG')


class DummyActionServer(ActionServer):
    '''Stores every message, sends nothing'''
    def __init__(self):
        super().__init__("dummy")
        self.received = []
        self.session = None
    def start(self, session):
        self.session = session
        self.t = t = threading.Thread(target=self.loop)
        t.start()
    
    def loop(self):
        while not self.session.closed:
            received = self.session.receiveChunk()
            if received:
                LOGGER.info("Dummy server (session %s) received a chunk of %s bytes", self.session.sid, len(received))
                self.received.append(received)
            if received is None:
                break
        
class EchoActionServer(ActionServer):
    '''Sends back the data that has been received'''
    def __init__(self):
        super().__init__("echo")
        self.session = None
    def start(self, session):
        print("Starting echo server, session", session.sid)
        self.session = session
        self.t = t = threading.Thread(target=self.loop)
        t.start()
    
    def loop(self):
        print("Echo server started, session", self.session.sid)
        while not self.session.closed:
            received = self.session.receiveChunk()
            if received:
                LOGGER.info("Echo server (session %s) received a chunk of %s bytes", self.session.sid, len(received))
                self.session.send(received)
            if received is None:
                break
        
class EchoByteByByteActionServer(ActionServer):
    '''Sends back the data that has been received, after each return line'''
    def __init__(self):
        super().__init__("echo2")
        self.session = None
    def start(self, session):
        print("Starting echo server, session", session.sid)
        self.session = session
        self.t = t = threading.Thread(target=self.loop)
        t.start()
    
    def loop(self):
        print("Echo server started, session", self.session.sid)
        toreturn = bytearray()
        while not self.session.closed:
            received = self.session.receiveOneByte()
            if received is not None:
                print("Received: ", bytes([received]))
                toreturn.append(received)
                if received == 10:
                    self.session.send(toreturn)
                    # reset
                    toreturn = bytearray()
            else:
                break
        

class Test(unittest.TestCase):
    def setUp(self):
        self.toclose = []


    def tearDown(self):
        for tocl in self.toclose:
            try:
                tocl()
            except Exception as e:
                print(str(e), file=sys.stderr)
        time.sleep(1)


    def testFolderCommunication(self):
        sharedfolder = os.path.join(os.getcwd(), "reception")
        server = FolderCommServer("localhost-server", sharedfolder)
        client = FolderCommClient("localhost-client", sharedfolder)
        server.registerCapability(DummyActionServer())
        server.registerCapability(EchoActionServer())
        
        server.showCapabilities()
        
        self.assertEqual([server.rid], client.listServers())
        self.assertEqual(set(['echo', 'dummy']), set(client.capabilities(server.rid)))
        
        threading.Thread(target=server.serveForever).start()
        self.toclose.append(server.stop)

        session = client.openSession(server.rid, "echo")
        self.toclose.append(session.close)
        
        tosend = b'Hello world!'
        session.send(tosend)
        # wait for message to come back
        time.sleep(1)
        data = session.receiveChunk()
        self.assertEqual(data, tosend)
    
    def testFolderCommunicationByteByByte(self):
        sharedfolder = os.path.join(os.getcwd(), "reception")
        server = FolderCommServer("localhost-server2", sharedfolder)
        client = FolderCommClient("localhost-client2", sharedfolder)
        server.registerCapability(DummyActionServer())
        server.registerCapability(EchoByteByByteActionServer())
        
        server.showCapabilities()
        
        self.assertEqual([server.rid], client.listServers())
        self.assertEqual(set(['echo2', 'dummy']), set(client.capabilities(server.rid)))
        
        threading.Thread(target=server.serveForever).start()
        self.toclose.append(server.stop)

        session = client.openSession(server.rid, "echo2")
        self.toclose.append(session.close)
        
        tosend = b'Hello world!'
        session.send(tosend)
        tosend2 = b'Hello world2!\n'
        session.send(tosend2)
        # wait for message to come back
        time.sleep(1)
        data = session.receiveChunk()
        self.assertEqual(data, tosend + tosend2)


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()