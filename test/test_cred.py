'''
Created on 31 mars 2020

@author: Cedric
'''
import unittest
import random

import os
import unittest.mock as mock

#import sys

#print(*sys.path, sep='\n')

from remoteconanywhere.cred import MyCredManager, CredentialManager, NetRcCredManager


import logging
logging.basicConfig()

class Test(unittest.TestCase):


    def setUp(self):
        pass


    def tearDown(self):
        pass



    def testMyCredManagerStatic(self):
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        alphabet = alphabet + alphabet.upper()+"0123456789'\"-_({)]=)"
        for _ in range(20):
            testpassword = "".join(random.sample(alphabet, random.randrange(10,20)))
            shadedeshade = MyCredManager.deshadepassword(MyCredManager.shadepassword(testpassword))
            self.assertEqual(testpassword, shadedeshade, testpassword + "!=" + shadedeshade)
            self.assertNotEqual(testpassword, MyCredManager.shadepassword(testpassword), testpassword + "==" + MyCredManager.shadepassword(testpassword))

    @mock.patch('getpass.getpass')
    @mock.patch('remoteconanywhere.cred.getinput')
    def testMyCredManager(self, inpu, getpw):
        getpw.return_value = 'apassword'
        inpu.return_value = 'auser'
        filename = "test.cred"
        cred = MyCredManager(file=filename, writeback=True)
        credentials = cred.getcredentials("test.host.name")
        self.assertEqual(credentials, ('auser', 'apassword'))
        self.assertTrue(os.path.exists(filename))
        inpu.return_value = 'another_user'
        # check that input() is not asked again
        credentials = cred.getcredentials("test.host.name")
        self.assertEqual(credentials, ('auser', 'apassword'))
        # check that input() is asked for another hostname
        credentials = cred.getcredentials("test.another.host.name")
        self.assertEqual(credentials, ('another_user', 'apassword'))
        os.remove(filename)



    @mock.patch('getpass.getpass')
    @mock.patch('remoteconanywhere.cred.getinput')
    def testNetRcManager(self, inpu, getpw):
        getpw.return_value = 'apassword'
        inpu.return_value = 'auser'
        filename = "test.cred"
        cred = NetRcCredManager(netrcfile=filename, writeback=True)
        credentials = cred.getcredentials("test.host.name")
        self.assertEqual(credentials, ('auser', 'apassword'))
        self.assertTrue(os.path.exists(filename))
        inpu.return_value = 'another_user'
        # check that input() is not asked again
        credentials = cred.getcredentials("test.host.name")
        self.assertEqual(credentials, ('auser', 'apassword'))
        # check that input() is asked for another hostname
        credentials = cred.getcredentials("test.another.host.name")
        self.assertEqual(credentials, ('another_user', 'apassword'))
        os.remove(filename)
        
    @mock.patch('getpass.getpass')
    @mock.patch('remoteconanywhere.cred.getinput')
    def testMyCredManager2(self, inpu, getpw):
        getpw.return_value = 'apassword'
        inpu.return_value = 'auser'
        filename = "test.cred"
        cred = MyCredManager(file=filename, writeback=True)
        credentials = cred.getcredentials("test.host.name")
        self.assertEqual(credentials, ('auser', 'apassword'))
        self.assertTrue(os.path.exists(filename))
        inpu.return_value = 'another_user'
        # destroy memory
        cred.hosts["test.host.name"] = (None, None)
        # check that input() is not asked again
        credentials = cred.getcredentials("test.host.name")
        self.assertEqual(credentials, ('another_user', 'apassword'))
        os.remove(filename)


    @mock.patch('getpass.getpass')
    @mock.patch('remoteconanywhere.cred.getinput')
    def testBasicCredManager(self, inpu, getpw):
        getpw.return_value = 'apassword'
        inpu.return_value = 'auser'
        cred = CredentialManager()
        credentials = cred.getcredentials("test.host.name")
        self.assertEqual(credentials, ('auser', 'apassword'))
        inpu.return_value = 'another_user'
        # check that input() is asked again
        credentials = cred.getcredentials("test.host.name")
        self.assertEqual(credentials, ('another_user', 'apassword'))
        # check that input() is asked for another hostname
        credentials = cred.getcredentials("test.another.host.name")
        self.assertEqual(credentials, ('another_user', 'apassword'))


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()