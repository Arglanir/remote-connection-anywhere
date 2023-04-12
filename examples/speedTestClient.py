#!/usr/bin/env python3
"""This script allows checking the speed of a connexion."""
import sys
import socket, logging

# configuring logging
logging.basicConfig(level='INFO', format='%(asctime)-15s %(levelname)-5s [%(threadName)s] %(module)s.%(funcName)s %(message)s',
    handlers=[logging.FileHandler("debug.log",mode="w"), logging.StreamHandler()])

from remoteconanywhere.speed import runSpeedClient, CAPA_SPEED
from remoteconanywhere.folder import FolderCommClient

def main(folder='.', rid=None):
    client = FolderCommClient("clientOn" + socket.gethostname().replace('-', ''), folder)
    if rid is None:
        servers = client.listServers()
        possible_servers = []
        for server in servers:
            capa = client.capabilities(server)
            if CAPA_SPEED in capa:
                possible_servers.append(server)
        if not possible_servers or len(possible_servers) > 1:
            print("Please select one server among:", *possible_servers)
            rid = input()
        else:
            rid = possible_servers[0]
            print("Selecting server", rid)
    session = client.openSession(rid, CAPA_SPEED)
    runSpeedClient(session)

    
if __name__ == "__main__":
    main(*sys.argv[1:])