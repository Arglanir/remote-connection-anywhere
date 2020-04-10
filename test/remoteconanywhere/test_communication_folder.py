'''
Created on 4 avr. 2020

@author: Cedric
'''
import unittest
from remoteconanywhere.communication import EchoActionServer, EchoByteByByteActionServer, StoreAllActionServer
from remoteconanywhere.folder import FolderCommClient, FolderCommServer
import os
import sys
import threading
import time

def patch_os_remove():
    temp = os.remove
    def new_remove(*args, **kwargs):
        print("Removing", *args)
        temp(*args, **kwargs)
    os.remove = new_remove
patch_os_remove()

import logging
logging.basicConfig(level='DEBUG')



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
        server.registerCapability(StoreAllActionServer())
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
        server.registerCapability(StoreAllActionServer())
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