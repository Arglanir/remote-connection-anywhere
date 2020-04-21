'''
This module allows using a FTP server to communicate.

Created on 13 avr. 2020

@author: Cedric
'''

from remoteconanywhere.communication import CommunicationSession, CommunicationServer, CommunicationClient
from ftplib import FTP, FTP_TLS, FTP_PORT
from remoteconanywhere.cred import CredentialManager
import fnmatch, logging
from io import BytesIO

import os
import ftplib
LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))

def createFtpConnection(folder, hostname, credmanager, port=FTP_PORT, tls=False):
    user, pwd = credmanager.getcredentials(hostname)
    if tls:
        ftp = FTP_TLS()
    else:
        ftp = FTP()
    LOGGER.info("Connecting to %s", hostname)
    ftp.connect(hostname, port)
    if tls:
        ftp.prot_p()
    ftp.login(user, pwd)
    try:
        ftp.cwd(folder)
    except:
        ftp.mkd(folder)
        ftp.cwd(folder)
    return ftp

class FtpCommunicationSession(CommunicationSession):
    
    FILENAMESTEMPLATE = "{me},{other},{sid},{sent}.bin"
    FILENAMERTEMPLATE = "{other},{me},{sid},{received}.bin"
    TOFROMANY = 'ANY'
    
    def __init__(self, me, other, sid, ftp):
        super().__init__(me, other, sid)
        self.alreadyProcessed = set()
        self.ftp = ftp
    
    def sendUnit(self, data):
        '''Send some data'''
        filename = self.FILENAMESTEMPLATE.format(**self.__dict__)
        filenametmp = "."+filename+".tmp"
        try:
            self.ftp.delete(filename)
            self.ftp.delete(filenametmp)
        except:
            pass
        self.sent += 1
        self.ftp.storbinary('STOR ' + filenametmp, BytesIO(data))
        self.ftp.rename(filenametmp, filename)
    
    @property
    def nextReceptionFileName(self):
        return self.FILENAMERTEMPLATE.format(**self.__dict__)
    
    def checkIfDataAvailable(self):
        '''Returns True if a new chunk is available, False otherwise'''
        try:
            toreturn = self.ftp.size(self.nextReceptionFileName) is not None
        except ftplib.Error:
            toreturn = False
        if toreturn:
            LOGGER.info("File %s exists.", self.nextReceptionFileName)
        return toreturn
    
    def discover(self, onlyOne=False):
        '''@return a list of [('other', b'data')]'''
        filenamewithstar = self.FILENAMERTEMPLATE.format(other='*', me=self.me, sid=self.sid, received=0)
        toreturn = []
        for fil in self.ftp.nlst():
            if fnmatch.fnmatch(fil, filenamewithstar):
                otherid = fil.split(',' + self.me)[0]
                towrite = bytearray()
                self.ftp.retrbinary('RETR ' + fil, towrite.extend)
                toreturn.append((otherid, towrite))
                # file is only for me, deleted
                self.ftp.delete(fil)
                if onlyOne:
                    return toreturn
        filenamewithdoublestar = self.FILENAMERTEMPLATE.format(other='*', me=self.TOFROMANY, sid=self.sid, received=0)
        for fil, facts in self.ftp.mlsd(facts=['modify']):
            if fnmatch.fnmatch(fil, filenamewithdoublestar):
                key = fil + facts['modify']
                if key in self.alreadyProcessed: continue
                otherid = fil.split(',')[0]
                towrite = bytearray()
                self.ftp.retrbinary('RETR ' + fil, towrite.extend)
                toreturn.append((otherid, towrite))
                # no deletion as it is also for other targets, but do not process again
                self.alreadyProcessed.add(key)
                if onlyOne:
                    return toreturn
        if toreturn:
            LOGGER.debug("Discovered messages for %s (session %s): %s", self.me, self.sid,
                         ", ".join('%s sent %s bytes' % (k, len(j)) for k, j in toreturn)
                         )
        return toreturn
    
    def deleteLastMessage(self):
        self.sent -= 1
        filename = self.FILENAMESTEMPLATE.format(**self.__dict__)
        self.ftp.delete(filename)
    
    def receiveRawChunk(self):
        '''Receives some data (one chunk)
        @return: None if no more data available, a bytes if data available (possibly empty)'''
        if self.closed:
            return None
        filename = self.nextReceptionFileName
        toreturn = b''
        try:
            fileexists = self.ftp.size(filename) is not None
        except (ftplib.Error, AttributeError):
            fileexists = False
        if not fileexists:
            LOGGER.debug("File %s doesn't exist.", filename)
        if fileexists:
            toreturn = bytearray()
            self.ftp.retrbinary('RETR ' + filename, toreturn.extend)
            self.ftp.delete(filename)
            self.received += 1
        # remember to increase received!
        return bytes(toreturn)
    
    def close(self, silently=False):
        super().close(silently)
        self.ftp.__exit__()

class FtpCommServer(CommunicationServer):
    
    CAPABILITYTEMPLATE = '{rid}.capa'
    
    def __init__(self, rid, ftpFactory, share=False):
        '''Initializes a server'''
        super().__init__(rid)
        self.ftpFactory = ftpFactory
        self.currentftp = None
        self.share = share
    
    @property
    def ftp(self):
        try:
            self.currentftp.pwd()
            return self.currentftp
        except:
            self.currentftp = self.ftpFactory()
            return self.currentftp
        
    def createSession(self, cid, rid, sid):
        return FtpCommunicationSession(rid, cid, sid, self.ftp if self.share else self.ftpFactory())
    
    @property
    def capabilityFile(self):
        filname = self.CAPABILITYTEMPLATE.format(rid=self.rid)
        return filname
    
    def showCapabilities(self):
        '''Show the capabilities (and that I'm alive)'''
        towrite = bytearray()
        for capa in self.capabilities:
            towrite.extend(capa.encode())
            towrite.extend(b'\n')
        LOGGER.info("Indicating capabilities of %s: %s bytes (%s capabilities)",
                    self.rid, len(towrite), len(self.capabilities))
        self.ftp.storbinary('STOR ' + self.capabilityFile, BytesIO(towrite))
    
    def stop(self):
        LOGGER.info("Stopping server %s", self.rid)
        super().stop()
        try:
            self.ftp.delete(self.capabilityFile)
        except ftplib.Error as e:
            LOGGER.warning("File %s doesn't exist anymore: %s", self.capabilityFile, e)
        self.ftp.__exit__()

class FtpCommClient(CommunicationClient):

    def __init__(self, cid, ftpFactory, share=False):
        super().__init__(cid)
        self.ftpFactory = ftpFactory
        self.currentftp = None
        self.share = share
    
    @property
    def ftp(self):
        try:
            self.currentftp.pwd()
            return self.currentftp
        except:
            self.currentftp = self.ftpFactory()
            return self.currentftp
    
    def createSession(self, cid, rid, sid):
        return FtpCommunicationSession(cid, rid, sid, self.ftp if self.share or sid in (0, '0') else self.ftpFactory())
    
    def listServers(self):
        '''List the servers rid'''
        toreturn = []
        for fil in self.ftp.nlst():
            if fnmatch.fnmatch(fil, FtpCommServer.CAPABILITYTEMPLATE.format(rid='*')):
                toreturn.append(fil.split('.')[0])
        return toreturn
    
    def capabilities(self, rid):
        '''Check the capabilities of a server'''
        towrite = bytearray()
        self.ftp.retrbinary('RETR ' + FtpCommServer.CAPABILITYTEMPLATE.format(rid=rid), towrite.extend)
        return towrite.decode('utf-8', errors='replace').split()

    