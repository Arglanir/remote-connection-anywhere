'''
Created on 8 avr. 2020

@author: Cedric
'''
import unittest
import sys
import time
import logging
from remoteconanywhere.pipe import *
from remoteconanywhere.communication import QueueCommunicationSession
import os

logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s %(module)s.%(funcName)s [%(threadName)s] %(message)s')

class Test(unittest.TestCase):

    def testSimpleReaderSync(self):
        actionserver = PipeActionServer(sys.executable, '-c', "print('Res:',1+1)")
        session = QueueCommunicationSession()
        mqueue = queue.Queue()
        mqueue.put(b'test\n')
        mqueue.put(b'titi')
        mqueue.put(None)
        actionserver.monoPipeReaderThreadByByteHelper(session, b'Header', mqueue, lambda:None)
        data = session.memoryGetSentData()
        self.assertEqual(b'Headertest\ntiti', data)

    def testSimpleReaderAsync(self):
        actionserver = PipeActionServer(sys.executable, '-c', "print('Res:',1+1)")
        session = QueueCommunicationSession()
        mqueue = queue.Queue()
        def todo():
            mqueue.put(b'test\n')
            time.sleep(0.2)
            mqueue.put(b'titi')
            time.sleep(0.2)
            mqueue.put(None)
        threading.Thread(target=todo).start()
        actionserver.monoPipeReaderThreadByByteHelper(session, b'Header', mqueue, lambda:None)
        data = session.memoryGetSentData()
        self.assertEqual(b'Headertest\n', data)
        data = session.memoryGetSentData()
        self.assertEqual(b'Headertiti', data)

    def testPythonPipeNonInteractive(self):
        # call program directly to check if output is correct
        args = [sys.executable, '-c', "print('Res:',1+1)"]
        expected = b'Res: 2'
        test = subprocess.check_output(args)
        self.assertIn(expected, test)
        
        # Ok, try with PipeActionServer
        #return
        actionserver = PipeActionServer(*args)
        session = QueueCommunicationSession()
        try:
            actionserver.start(session)
            time.sleep(2)
            # grogram is closed
            self.assertTrue(session.closed)
            # get data
            data = session.memoryGetSentData()
            self.assertIn(expected, data or b'Nothing received')
        finally:
            session.close()



    def testPythonPipeInteractive(self):
        #return
        actionserver = PipeActionServer(sys.executable, '-i', '-u')
        session = QueueCommunicationSession()
        try:
            actionserver.start(session)
            time.sleep(1)
            while True:
                data = session.memoryGetSentData()
                if not data:
                    break
                print(data.decode())
            session.memoryPutSomeData(b'1+1\n')
            time.sleep(1)
            data = session.memoryGetSentData()
            #self.assertIn(b'2', data)
            print(data)
            session.memoryPutSomeData(b'import sys\n')
            session.memoryPutSomeData(b'sys.exit(100)\n')
            time.sleep(1)
            sent = b''
            # read the rest
            while True:
                data = session.memoryGetSentData()
                if not data:
                    break
                sent += data
                print(data.decode())
            self.assertTrue(session.closed)
            # return code is present
            self.assertIn(b'100', sent)
            # message to close session is present
            self.assertIn(session.data_to_close_session, sent)
        finally:
            session.close()


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testPythonPipe']
    unittest.main()