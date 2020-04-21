'''
Created on 13 avr. 2020

@author: Cedric
'''
import unittest
from configurationoftests import ftpFactory, FOLDER_SHARED_WITH_FTP, FTPFOLDER
from remoteconanywhere.ftp import FtpCommClient, FtpCommServer, FtpCommunicationSession
from abstract_comm_test import AbstractCommTest
import os
from remoteconanywhere.folder import FolderCommServer, FolderCommClient

SHAREDFOLDER = os.path.join(os.getcwd(), "reception",FTPFOLDER)
if FOLDER_SHARED_WITH_FTP:
    os.makedirs(os.path.join(os.getcwd(), "reception"), exist_ok=True)
    def cleaning():
        for fil in os.listdir(SHAREDFOLDER):
            path = os.path.join(SHAREDFOLDER, fil)
            if os.path.isdir(path):
                os.rmdir(path)
            else:
                os.remove(path)
            print("File", fil, "still exists at the end.")
        os.rmdir(SHAREDFOLDER)
else:
    def cleaning():
        pass

class TestFtpCommunication(unittest.TestCase):
    def setUp(self):
        self.sess1 = FtpCommunicationSession('1', '2', 99, ftpFactory())
        self.sess2 = FtpCommunicationSession('2', '1', 99, ftpFactory())
    
    def tearDown(self):
        self.sess1.close(True)
        self.sess2.close(True)
        cleaning()

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

class TestFullFtp(AbstractCommTest):
    def setUp(self):
        self.skipTest("because")
        super().setUp()
        self.server = FtpCommServer("localhost-server", ftpFactory, share=False)
        self.client = FtpCommClient("localhost-client", ftpFactory, share=False)

    def tearDown(self):
        super().tearDown()
        cleaning()
    
    #skipped = True
    

class TestClientFtp(AbstractCommTest):
    def setUp(self):
        #self.skipTest("because")
        super().setUp()
        sharedfolder = SHAREDFOLDER
        self.server = FolderCommServer("localhost-server", sharedfolder)
        self.client = FtpCommClient("localhost-client", ftpFactory, share=False)
    def tearDown(self):
        super().tearDown()
        cleaning()
        
    if not FOLDER_SHARED_WITH_FTP:
        # cannot communicate with each other: skip it
        skipped = True




class TestServerFtp(AbstractCommTest):
    def setUp(self):
        super().setUp()
        sharedfolder = SHAREDFOLDER
        self.server = FtpCommServer("localhost-server", ftpFactory, share=False)
        self.client = FolderCommClient("localhost-client", sharedfolder)

    def tearDown(self):
        super().tearDown()
        cleaning()

    if not FOLDER_SHARED_WITH_FTP:
        # cannot communicate with each other: skip it
        skipped = True


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()