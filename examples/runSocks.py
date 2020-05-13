#!/usr/bin/env python3
"""This script allows running a socks backend through an IMAP connection"""
# import
import sys
import os
import logging, time

# extending python path
folder = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(folder, '..', 'src'))

# our imports
from remoteconanywhere.imap import *
from remoteconanywhere.socks import *
from remoteconanywhere.cred import MyCredManager
import remoteconanywhere.communication
from remoteconanywhere.pipe import GenericPipeActionServer

# reading arguments (you can do a fancier script with argparse...)
try:
    HOSTNAME = sys.argv[1]
except:
    print("Specify the host name as first argument.")
    sys.exit(1)

# configuring logging
logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s [%(threadName)s] %(module)s.%(funcName)s %(message)s',
    handlers=[logging.FileHandler("debug.log"), logging.StreamHandler()])

# configuration of IMAP
def imapFactory():
    return createImapClient(HOSTNAME, ssl=False, tls=True, credmanager=MyCredManager(os.path.join(folder, '.credentials'), True), folder='communication-socks')

# creating IMAP communication server
server = Imap4CommServer('sockson' + socket.gethostname().split('.')[0].replace('-', ''), imapFactory)

server.registerCapability(GenericPipeActionServer())
# registering both in same server, they do not consume anything
server.registerCapability(Socks5Backend())
server.registerCapability(Socks4Backend())

# configure timeouts/sleeps (no need of too many searches)
remoteconanywhere.communication.LOOP_SLEEP = 5
SocksFrontEnd.LOOP_TIMEOUT = 1
remoteconanywhere.pipe.LOOP_TIME = 3

#remoteconanywhere.imap.RESTART_AFTER=20
# cleaning
server.cleanUp()

# let's go!
try:
    server.serveForever()
finally:
    server.stop()
    time.sleep(1)
