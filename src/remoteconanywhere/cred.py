'''
Created on 31 mars 2020

@author: Cedric
'''

#import random

import getpass
import netrc
import json
import os
import base64
import zlib
import logging

LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))

# ##################################### CREDENTIALS

#         CCC RRR  EEEE DDD  EEEE N   N TTTTT III  AA  L    SSS
#        C    R  R E    D  D E    NN  N   T    I  A  A L   S
#        C    RRR  EEE  D  D EEE  N N N   T    I  AAAA L    SSS
#        C    R R  E    D  D E    N  NN   T    I  A  A L       S
#         CCC R  R EEEE DDD  EEEE N   N   T   III A  A LLLL SSS

def getinput(prompt):
    # maybe display dialog?
    return input(prompt)

class CredentialManager:
    """Base class for a PasswordManager, that always asks"""
    def __init__(self, *args, **kwargs):
        """Constructor"""
        pass
    def getcredentials(self, host, login=None):
        """@return a tuple (login, password) corresponding to host"""
        return self.badcredentials(host, login)
    def badcredentials(self, host, login=None):
        """@return a tuple (login, password) corresponding to host, in case the first ones where incorrect."""
        print("What credential should I use to connect to", host,"?")
        inputlogin = getinput("".join(("Login", "" if not login else " [default: %s]" % login, ": "))) or login
        password = getpass.getpass("Password: ")
        return (inputlogin, password)

class NetRcCredManager(CredentialManager):
    def __init__(self, netrcfile=None, writeback=False):
        """Constructor."""
        super().__init__()
        self.netrcfile = netrcfile or os.path.join(os.environ['HOME'], ".netrc")
        if not os.path.exists(self.netrcfile):
            open(self.netrcfile, "wb").close()
            os.chmod(self.netrcfile, 0o600)
        self.netrc = netrc.netrc(netrcfile)
        self.writeback = writeback
    def getcredentials(self, host, login=None):
        """@return a tuple (login, password) corresponding to host"""
        known = self.netrc.authenticators(host)
        if known is None:
            print("No entry for", host, "in", self.netrcfile)
            return self.badcredentials(host, login)
        inputlogin, _, password = known
        inputlogin = login or inputlogin
        if password is None:
            print("Password missing for %s@%s" % (inputlogin, host))
            return self.badcredentials(host, inputlogin)
        return (inputlogin, password)
    def badcredentials(self, host, login=None):
        """@return a tuple (login, password) corresponding to host, in case the first ones where incorrect."""
        login, password = super().badcredentials(host, login)
        self.netrc.hosts[host] = (login, self.netrc.hosts.get(host, (None,)*3)[1], password)
        if self.writeback:
            with open(self.netrcfile, "wb") as fout:
                fout.write(repr(self.netrc).encode("utf-8"))
                print("File", self.netrcfile, "has been rewritten.")
        return login, password

class MyCredManager(CredentialManager):
    def __init__(self, file=None, writeback=False):
        """Constructor."""
        super().__init__()
        self.file = file or os.path.join(os.environ['HOME'], "."+os.path.basename(__file__).replace(".py", ".cred"))
        if not os.path.exists(self.file):
            open(self.file, "w").close()
            os.chmod(self.file, 0o600)
        self.hosts = {}
        with open(self.file, "r") as fin:
            try:
                self.hosts = json.load(fin)
            except ValueError as e:
                LOGGER.warning("Error loading file %s: %r", self.file, e)
        self.writeback = writeback

    @staticmethod
    def deshadepassword(shadedpassword):
        b = base64.b64decode(shadedpassword)
        dz = zlib.decompress(zlib.decompress(b))
        p = dz.decode('utf-8')
        return p
    @staticmethod
    def shadepassword(password):
        b = password.encode('utf-8')
        z = zlib.compress(zlib.compress(b))
        e = base64.b64encode(z).decode()
        return e

    def getcredentials(self, host, login=None):
        """@return a tuple (login, password) corresponding to host"""
        known = self.hosts.get(host)
        if known is None:
            print("No entry for", host, "in", self.file)
            return self.badcredentials(host, login)
        inputlogin, shadedpassword = known
        inputlogin = login or inputlogin
        if shadedpassword is None:
            print("Password missing for %s@%s" % (inputlogin, host))
            return self.badcredentials(host, inputlogin)
        password = self.deshadepassword(shadedpassword)
        return (inputlogin, password)
    
    def badcredentials(self, host, login=None):
        """@return a tuple (login, password) corresponding to host, in case the first ones where incorrect."""
        login, password = super().badcredentials(host, login)
        self.hosts[host] = (login, self.shadepassword(password))
        if self.writeback:
            with open(self.file, "w") as fout:
                json.dump(self.hosts, fout)
                print("File", self.file, "has been rewritten.")
        return login, password

# list of credential managers
CREDENTIAL_MANAGERS = {
    "NETRC":NetRcCredManager,
    "DEFAULT": MyCredManager,
    "ASK": CredentialManager
}