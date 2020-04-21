'''
Created on 13 avr. 2020

@author: Cedric
'''

from remoteconanywhere.ftp import createFtpConnection
from remoteconanywhere.cred import MyCredManager
import os

CREDFILE = os.path.join(os.path.dirname(__file__), "credentials.json")
FTPFOLDER = "testcomm"
# indicate if the folder communication and FTP communication can work together
# for that, FTPFOLDER must be in the folder reception/
FOLDER_SHARED_WITH_FTP = True

def ftpFactory():
    return createFtpConnection(FTPFOLDER, "127.0.0.1", MyCredManager(CREDFILE, True))
