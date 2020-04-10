'''
Created on 4 avr. 2020

@author: Cedric
'''
import unittest
from remoteconanywhere.communication import QueueCommunicationSession
import os
import threading
import time
import sys

import logging
logging.basicConfig(level='DEBUG')


class Test(unittest.TestCase):

    def testQueueCommSession(self):
        session = QueueCommunicationSession()
        
        # send data
        sent = b'Hello World!'
        session.memoryPutSomeData(sent)
        received = session.receiveChunk()
        self.assertEqual(sent, received)
        
        # received data
        sent = b'Hello from here too'
        session.send(sent)
        data = session.memoryGetSentData()
        self.assertEqual(sent, data)
        
        # receive data byte by byte
        session.memoryPutSomeData(b'012345')
        session.memoryPutSomeData(b'6789')
        self.assertEqual(b'0', session.receiveOneByte())
        self.assertEqual(b'1', session.receiveOneByte())
        self.assertEqual(b'2', session.receiveOneByte())
        self.assertEqual(b'3', session.receiveOneByte())
        self.assertEqual(b'4', session.receiveOneByte())
        self.assertEqual(b'5', session.receiveOneByte())
        self.assertEqual(b'6', session.receiveOneByte())
        self.assertEqual(b'7', session.receiveOneByte())
        self.assertEqual(b'8', session.receiveOneByte())
        self.assertEqual(b'9', session.receiveOneByte())
        self.assertEqual(None, session.receiveOneByte(timeout=0.01))
        
        session.close()
        self.assertEqual(None, session.receiveOneByte())
        
        
    
    def testQueueCommSessionEndFromOtherSide(self):
        session = QueueCommunicationSession()
        
        # send data
        sent = b'Hello World!'
        session.memoryPutSomeData(sent)
        received = session.receiveChunk()
        self.assertEqual(sent, received)
        
        self.assertFalse(session.closed)
        session.memoryPutSomeData(session.data_to_close_session)
        # try to receive something
        self.assertEqual(None, session.receiveOneByte())
        self.assertTrue(session.closed)
        
    def testQueueCommSessionLinked(self):
        sessionClient = QueueCommunicationSession('client')
        sessionServer = QueueCommunicationSession('server')
        sessionClient.inexorablyLinkQueue(sessionServer)
        tosend = b'Hello world'
        sessionClient.send(tosend)
        time.sleep(0.2)
        data = sessionServer.receiveChunk()
        self.assertEqual(data, tosend)
        sessionServer.close()
        time.sleep(0.2)
        # receive some data to check that session is closed
        data = sessionClient.receiveChunk()
        self.assertTrue(sessionClient.closed)
        self.assertEqual(data, None)

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()