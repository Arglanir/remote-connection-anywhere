'''
Created on 23 avr. 2020

@author: Cedric
'''
import unittest
import abstract_comm_test
from configurationoftests import imapFactory
from remoteconanywhere.imap import ImapCommSession , Imap4CommServer,\
    Imap4CommClient

class TestImapComm(unittest.TestCase):

    def setUp(self):
        self.sess1 = ImapCommSession('1', '2', 99, imapFactory())
        self.sess2 = ImapCommSession('2', '1', 99, imapFactory())
    
    def tearDown(self):
        self.sess1.close(True)
        self.sess2.close(True)

    def testSimpleCommunication(self):
        tosend = b"Some data"
        self.assertFalse(self.sess2.checkIfDataAvailable(), "data available??")
        self.sess1.send(tosend)
        self.assertTrue(self.sess2.checkIfDataAvailable(), "No data seems available")
        chunk = self.sess2.receiveChunk()
        self.assertEqual(tosend, chunk)
        self.assertEqual(b'', self.sess2.receiveChunk())
        self.assertEqual(b'', self.sess1.receiveChunk())
        tosend = b"Some data in return"
        self.assertFalse(self.sess1.checkIfDataAvailable(), "data available??")
        self.sess2.send(tosend)
        self.assertTrue(self.sess1.checkIfDataAvailable(), "No data seems available")
        chunk = self.sess1.receiveChunk()
        self.assertEqual(tosend, chunk)
        self.assertFalse(self.sess1.checkIfDataAvailable(), "data available??")
        self.assertFalse(self.sess2.checkIfDataAvailable(), "data available??")
        self.assertEqual(b'', self.sess2.receiveChunk())
        self.assertEqual(b'', self.sess1.receiveChunk())
        
        
    def testSimpleCommunication2(self):
        tosend = b"Some data"
        self.assertFalse(self.sess2.checkIfDataAvailable(), "data available??")
        self.assertEqual(None, self.sess2.receiveOneByte(0.01))
        self.sess1.send(tosend)
        self.assertTrue(self.sess2.checkIfDataAvailable(), "No data seems available")
        self.assertEqual(b'S', self.sess2.receiveOneByte(0.01))
        self.assertEqual(b'o', self.sess2.receiveOneByte(0.01))
        self.assertEqual(b'm', self.sess2.receiveOneByte(0.01))
        self.assertEqual(b'e', self.sess2.receiveOneByte(0.01))
        self.assertEqual(b' ', self.sess2.receiveOneByte(0.01))
        self.assertEqual(b'd', self.sess2.receiveOneByte(0.01))
        self.assertEqual(b'a', self.sess2.receiveOneByte(0.01))
        self.assertEqual(b't', self.sess2.receiveOneByte(0.01))
        self.assertEqual(b'a', self.sess2.receiveOneByte(0.01))
        self.assertEqual(None, self.sess2.receiveOneByte(0.01))

class TestFullImap(abstract_comm_test.AbstractCommTest):
    def setUp(self):
        #self.skipTest("because")
        super().setUp()
        self.server = Imap4CommServer("localhost-server", imapFactory)
        self.client = Imap4CommClient("localhost-client", imapFactory)

    def tearDown(self):
        super().tearDown()
        #cleaning()
    

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()