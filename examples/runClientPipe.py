#!/usr/bin/env python3
"""This script allows running program frontend through an IMAP connection"""

# imports
import socket, sys, time
import logging
import sys
import os

# extending path
folder = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(folder, '..', 'src'))


# our imports
from remoteconanywhere.imap import *
from remoteconanywhere.pipe import *
from remoteconanywhere.cred import MyCredManager
import remoteconanywhere.communication

remoteconanywhere.pipe.LOOP_TIME = 3
CREDMANAGER = MyCredManager(os.path.join(folder, '.credentials'), True)
# read arguments
try:
    HOSTNAME = sys.argv[1]
except:
    try:
        hosts = CREDMANAGER.knownhosts()
        if len(hosts) > 1:
            print("Select hosts between", *hosts)
            raise Exception
        HOSTNAME = hosts[0]
    except:
        print("Specify the host name as first argument.")
        sys.exit(1)

# configuring logging
logging.basicConfig(level='INFO', format='%(asctime)-15s %(levelname)-5s [%(threadName)s] %(module)s.%(funcName)s %(message)s')

# configuring imap
def imapFactory():
    return createImapClient(HOSTNAME, ssl=False, tls=True, credmanager=CREDMANAGER, folder='communication-socks')


# imap communication client
client = Imap4CommClient('pipeclienton' + socket.gethostname().split('.')[0].replace('-', ''), imapFactory)

# finding the right server to contact
servers = client.listServers()
possibilities = dict()
for rid in servers:
    capa = client.capabilities(rid)
    capapipe = [k for k in capa if k.startswith('pipe')]
    if capapipe:
        print("Server", rid, "proposes", capapipe)
        possibilities[rid] = capapipe
if not possibilities:
    print("No pipe server found.")
    sys.exit(1)

# selecting it
if len(possibilities) == 1:
    rid = possibilities.keys().__iter__().__next__()
else:
    rid = None
    while rid not in possibilities:
        print("Select server: ", end="")
        rid = input().strip()

if len(possibilities[rid]) == 1:
    capa = possibilities[rid][0]
else:
    capa = None
    while capa not in possibilities[rid]:
        print("Select pipe type: ", end="")
        capa = input().strip()

# starting all
session = client.openSession(rid, capa)
pclient = PipeLineClient(session)
pclient.start()

