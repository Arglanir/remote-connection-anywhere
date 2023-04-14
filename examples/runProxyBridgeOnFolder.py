#!/usr/bin/env python3
'''This script listens for incoming connections and forwards everything to a folder communication canal.
You can use it using serveOwnProxyOnFolder.py on the remote part.
'''

import logging; logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s [%(threadName)s] %(module)s.%(funcName)s %(message)s',
    handlers=[logging.FileHandler("debug.log",mode="w"), logging.StreamHandler()])


from remoteconanywhere.folder import FolderCommClient
import socket, sys
from remoteconanywhere.socket import runLocalServerForRemoteClient


def main(folder='.', port=8002):
    '''Main method, rather easy'''
    if folder in ['-h', '--help']:
        print("Usage: program [folder] [port]")
        print("Will create a folder communication, to a distant remote host")
        return
    client = FolderCommClient("clientOn" + socket.gethostname().replace('-', ''), folder)
    print("Local server will soon be running on port", port)
    print("If it is connected to a proxy, you may run\n  export {http,https}_proxy=http://localhost:%s; export {HTTP,HTTPS}_PROXY=$http_proxy" % port)
    runLocalServerForRemoteClient(port, client)


if __name__ == '__main__':
    main(*sys.argv[1:])
