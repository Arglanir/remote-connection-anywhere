'''
Created on 4 avr. 2020

@author: Cedric
'''
import unittest
from remoteconanywhere.folder import FolderCommClient, FolderCommServer
from abstract_comm_test import AbstractCommTest
import os

def patch_os_remove():
    temp = os.remove
    def new_remove(*args, **kwargs):
        print("Removing", *args)
        temp(*args, **kwargs)
    os.remove = new_remove
patch_os_remove()

class TestFolderComm(AbstractCommTest):
    def setUp(self):
        super().setUp()
        self.sharedfolder = sharedfolder = os.path.join(os.getcwd(), "reception")
        self.server = FolderCommServer("localhost-server", sharedfolder)
        self.client = FolderCommClient("localhost-client", sharedfolder)


    def tearDown(self):
        super().tearDown()
        for fil in os.listdir(self.sharedfolder):
            path = os.path.join(self.sharedfolder, fil)
            if os.path.isdir(path):
                os.rmdir(path)
            else:
                os.remove(path)
            print("File", fil, "still exists at the end.")
        os.rmdir(self.sharedfolder)


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()