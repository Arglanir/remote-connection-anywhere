'''
Created on 31 mars 2020

@author: Cedric
'''
import unittest

from remoteconanywhere.socket_proxy import *

class Test(unittest.TestCase):
    def setUp(self):
        pass


    def tearDown(self):
        pass


    def testProxy(self):
        port = findFreePort()
        port2 = findFreePort(port)
        self.assertNotEqual(port, port2)
        


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()