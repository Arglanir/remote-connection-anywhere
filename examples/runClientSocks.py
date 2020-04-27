#!/usr/bin/env python3
"""This script allows running a socks frontend through an IMAP connection"""
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
from remoteconanywhere.socks import *
from remoteconanywhere.cred import MyCredManager
import remoteconanywhere.communication


# read arguments
try:
    HOSTNAME = sys.argv[1]
except:
    print("Specify the host name as first argument.")
    sys.exit(1)

try:
    PORT = sys.argv[2]
except:
    PORT = findFreePort()

# configuring logging
logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s [%(threadName)s] %(module)s.%(funcName)s %(message)s')

# configuring imap
def imapFactory():
    return createImapClient(HOSTNAME, ssl=False, tls=True, credmanager=MyCredManager(os.path.join(folder, '.credentials'), True), folder='communication-socks')

# imap communication client
client = Imap4CommClient('socksclienton' + socket.gethostname().split('.')[0].replace('-', ''), imapFactory)

# finding the right server to contact
servers = client.listServers()
socksrid = [ rid for rid in servers if SocksFrontEnd.CAPA in client.capabilities(rid) ]

print("Found", SocksFrontEnd.CAPA, "in", socksrid)

if not socksrid or len(socksrid) > 1:
    print("Cannot proceed.")
    sys.exit(1)

port = PORT

print("Using port", port)

# socks frontend
sockslocalfrontend = SocksFrontEnd(client, port, *socksrid)
# longer loop times
remoteconanywhere.communication.LOOP_SLEEP = 5
sockslocalfrontend.LOOP_TIMEOUT = 1
sockslocalfrontend.DATA_TIMEOUT = 3

# let's go!
sockslocalfrontend.start()

# write some information
with open("environment_linux", "w") as fout:
    fout.write("export http_proxy=socks4h://localhost:")
    fout.write("%s" % port)
    fout.write("\n")
    fout.write("""export {https,ftp,rsync,all}_proxy=$http_proxy\n""")
    fout.write("""export {HTTP,HTTPS,FTP,RSYNC,ALL}_PROXY=$http_proxy\n""")
    fout.write("""echo "For curl: curl -k --socks4a localhost:%s http://something"\n""" % port)
    fout.write("""echo "For git: git config http.sslVerify false; git config --global http.proxy '$http_proxy'"\n""")
    print("  In a terminal, type the following in order to use the proxy:")
    print("  source", os.path.abspath('environment_linux'))

# local loop, waiting for ctrl+c
try:
    while True:
        time.sleep(10)
except:
    sockslocalfrontend.stop()

