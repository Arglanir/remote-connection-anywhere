#!/usr/bin/env python3
"""This script allows checking the speed of a connexion, as a server."""

import sys
import socket, logging, time

# configuring logging
logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s [%(threadName)s] %(module)s.%(funcName)s %(message)s',
    handlers=[logging.FileHandler("debug.log",mode="w"), logging.StreamHandler()])

from remoteconanywhere.speed import SpeedActionServer
from remoteconanywhere.folder import FolderCommServer

def main(folder='.'):
    server = FolderCommServer("serverOn" + socket.gethostname().replace('-', ''), folder)
    server.registerCapability(SpeedActionServer())
    
    server.cleanUp()

    # let's go!
    try:
        server.serveForever()
    finally:
        server.stop()
        server.cleanUp()
        time.sleep(1)

    
if __name__ == "__main__":
    main(*sys.argv[1:])
