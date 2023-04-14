#!/usr/bin/env python3
'''This script serves the current environment proxy to a folder.
On the client, use runProxyBridgeOnFolder.py'''

import sys, os, re
import logging; logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s [%(threadName)s] %(module)s.%(funcName)s %(message)s',
    handlers=[logging.FileHandler("debug.log",mode="w"), logging.StreamHandler()])
from remoteconanywhere.folder import FolderCommServer
from remoteconanywhere.socket import LocalhostTcpSocketActionServer, TcpSocketActionServer
import socket


def detectProxy():
    '''Detects the proxy and return its hostname:port'''
    prox = os.getenv('http_proxy')
    if not prox:
        raise ValueError("Impossible to find proxy")
    if '@' in prox:
        prox = prox.split('@')[1]
    else:
        prox = prox.split('//')[1]
    prox = prox.rstrip('/')
    return prox

def mainExec(folder='.', addr=None):
    '''Main method for the server.'''
    if addr is None:
        addr = detectProxy()
    if ':' not in addr:
        addr = 'localhost:%s' % addr
    # split
    host, port = addr.split(':')
    port = int(port)
    # create server and run it
    server = FolderCommServer("serverOn" + socket.gethostname().replace('-', ''), folder)
    server.cleanUp()
    server.registerCapability(TcpSocketActionServer(host, port))
    server.serveForever()
    

def main(*args):
    '''Main that checks the arguments.'''
    if '-h' in args or '--help' in args:
        print("Usage: program [folder] [host:port]")
        print("Will create a folder communication, by default serving the proxy at:")
        print(detectProxy())
        return
    mainExec(*args)
    
if __name__ == '__main__':
    main(*sys.argv[1:])
