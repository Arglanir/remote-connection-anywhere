'''
Created on 4 avr. 2020

@author: Cedric
'''
import unittest
from remoteconanywhere.communication import EchoActionServer, EchoByteByByteActionServer, StoreAllActionServer
import sys
import threading
import time
import logging


logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s %(module)s.%(funcName)s [%(threadName)s] %(message)s')


class AbstractCommTest(unittest.TestCase):
    skipped = False
    def __init__(self, methodName='runTest'):
        unittest.TestCase.__init__(self, methodName=methodName)
        # remove run if still abstract
        if self.__class__ != AbstractCommTest and not self.skipped:
            # Rebind `run' from the parent class.
            self.run = lambda *args, **kwargs: unittest.TestCase.run( self, *args, **kwargs)
        else:
            print("Test", self.__class__, "skipped")
            self.run = lambda *args, **kwargs: None
        
    def setUp(self):
        self.server = None
        self.client = None
        self.toclose = []
        # concrete class must update server and client


    def tearDown(self):
        for tocl in self.toclose:
            try:
                tocl()
            except Exception as e:
                print(str(e), file=sys.stderr)
        time.sleep(1)


    def testBasicCommunication(self):
        server = self.server
        client = self.client
        server.registerCapability(StoreAllActionServer())
        server.registerCapability(EchoActionServer())
        
        server.showCapabilities()
        
        self.assertEqual([server.rid], list(client.listServers()))
        self.assertEqual(set(['echo', 'dummy']), set(client.capabilities(server.rid)))
        
        threading.Thread(target=server.serveForever, name="server-thread").start()
        self.toclose.append(server.stop)

        session = client.openSession(server.rid, "echo")
        self.toclose.append(session.close)
        
        tosend = b'Hello world!'
        session.send(tosend)
        # wait for message to come back
        time.sleep(1)
        data = session.receiveChunk()
        self.assertEqual(data, tosend)
    
    def testBasicCommunicationByteByByte(self):
        server = self.server
        client = self.client
        server.registerCapability(StoreAllActionServer())
        server.registerCapability(EchoByteByByteActionServer())
        
        server.showCapabilities()
        
        self.assertEqual([server.rid], list(client.listServers()))
        self.assertEqual(set(['echo2', 'dummy']), set(client.capabilities(server.rid)))
        
        threading.Thread(target=server.serveForever, name="server-thread").start()
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