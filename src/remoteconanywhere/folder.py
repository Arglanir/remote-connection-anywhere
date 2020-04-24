'''
Contains all is needed for a communication to be established through a shared folder.

Created on 10 avr. 2020

@author: Cedric
'''
from remoteconanywhere.communication import CommunicationSession, CommunicationServer, CommunicationClient
import os, fnmatch, logging


LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))


class FolderCommunicationSession(CommunicationSession):
    
    FILENAMESTEMPLATE = "{me},{other},{sid},{sent}.bin"
    FILENAMERTEMPLATE = "{other},{me},{sid},{received}.bin"
    TOFROMANY = 'ANY'
    
    def __init__(self, me, other, sid, folderReception, folderEmission):
        if folderEmission is None:
            folderEmission = folderReception
        super().__init__(me, other, sid)
        self.folderReception = folderReception
        self.folderEmission = folderEmission
        self.alreadyProcessed = set()
    
    def sendUnit(self, data):
        '''Send some data'''
        filename = self.FILENAMESTEMPLATE.format(**self.__dict__)
        filenametmp = "."+filename+".tmp"
        final = os.path.join(self.folderEmission, filename)
        temporary = os.path.join(self.folderEmission, filenametmp)
        if os.path.exists(final):os.remove(final)
        self.sent += 1
        with open(temporary, "wb") as fout:
            fout.write(data)
        os.rename(temporary, final)
    
    @property
    def nextReceptionFileName(self):
        return self.FILENAMERTEMPLATE.format(**self.__dict__)
    
    def checkIfDataAvailable(self):
        '''Returns True if a new chunk is available, False otherwise'''
        return os.path.exists(os.path.join(self.folderReception, self.nextReceptionFileName))
    
    def discover(self, onlyOne=False):
        '''@return a list of [('other', b'data')]'''
        filenamewithstar = self.FILENAMERTEMPLATE.format(other='*', me=self.me, sid=self.sid, received=0)
        toreturn = []
        for fil in os.listdir(self.folderReception):
            if fnmatch.fnmatch(fil, filenamewithstar):
                otherid = fil.split(',' + self.me)[0]
                filepath = os.path.join(self.folderReception, fil)
                with open(filepath, 'rb') as fin:
                    toreturn.append((otherid, fin.read()))
                # file is only for me, deleted
                os.remove(filepath)
                if os.path.exists(filepath):
                    LOGGER.warning("Deleted discovered file %s but seems to be still there", filepath)
                else:
                    LOGGER.debug("Really deleted discovered file %s", filepath)
                if onlyOne:
                    return toreturn
        filenamewithdoublestar = self.FILENAMERTEMPLATE.format(other='*', me=self.TOFROMANY, sid=self.sid, received=0)
        for fil in os.listdir(self.folderReception):
            if fnmatch.fnmatch(fil, filenamewithdoublestar):
                key = fil + os.path.getmtime(filepath)
                if key in self.alreadyProcessed: continue
                otherid = fil.split(',')[0]
                filepath = os.path.join(self.folderReception, fil)
                with open(filepath, 'rb') as fin:
                    toreturn.append((otherid, fin.read()))
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
        realfile = os.path.join(self.folderEmission, filename)
        os.remove(realfile)
        if os.path.exists(realfile):
            LOGGER.warning("Deleted last message %s but seems to be still there", realfile)
        else:
            LOGGER.debug("Really deleted last file %s", realfile)
    
    def receiveRawChunk(self):
        '''Receives some data (one chunk)
        @return: None if no more data available, a bytes if data available (possibly empty)'''
        if self.closed:
            return None
        filename = self.nextReceptionFileName
        realfile = os.path.join(self.folderReception, filename)
        toreturn = b''
        if os.path.exists(realfile):
            with open(realfile, "rb") as fin:
                toreturn = fin.read()
            os.remove(realfile)
            if os.path.exists(realfile):
                LOGGER.warning("Deleted file %s but seems to be still there", realfile)
            else:
                LOGGER.debug("Really deleted file %s", realfile)
            self.received += 1
        # remember to increase received!
        return toreturn

class FolderCommServer(CommunicationServer):
    
    CAPABILITYTEMPLATE = '{rid}.capa'
    
    def __init__(self, rid, folderReception, folderEmission=None):
        '''Initializes a server'''
        if folderEmission is None:
            folderEmission = folderReception
        self.folderReception = folderReception
        self.folderEmission = folderEmission
        for dire in (folderEmission, folderReception):
            if not os.path.exists(dire):
                os.makedirs(dire)
        super().__init__(rid)
    
    def createSession(self, cid, rid, sid):
        return FolderCommunicationSession(rid, cid, sid, self.folderReception, self.folderEmission)
    
    @property
    def capabilityFile(self):
        filname = self.CAPABILITYTEMPLATE.format(rid=self.rid)
        return os.path.join(self.folderEmission, filname)
    
    def showCapabilities(self):
        '''Show the capabilities (and I'm alive)'''
        with open(self.capabilityFile, 'w') as fout:
            for capa in self.capabilities:
                fout.write(capa)
                fout.write('\n')
    
    def stop(self):
        super().stop()
        os.remove(self.capabilityFile)

class FolderCommClient(CommunicationClient):

    def __init__(self, cid, folderReception, folderEmission=None):
        super().__init__(cid)
        if folderEmission is None:
            folderEmission = folderReception
        self.folderReception = folderReception
        self.folderEmission = folderEmission
        for dire in (folderEmission, folderReception):
            if not os.path.exists(dire):
                os.makedirs(dire)
    
    def createSession(self, cid, rid, sid):
        return FolderCommunicationSession(cid, rid, sid, self.folderReception, self.folderEmission)
    
    def listServers(self):
        '''List the servers rid'''
        toreturn = []
        for fil in os.listdir(self.folderReception):
            if fnmatch.fnmatch(fil, FolderCommServer.CAPABILITYTEMPLATE.format(rid='*')):
                toreturn.append(fil.split('.')[0])
        return toreturn
    
    def capabilities(self, rid):
        '''Check the capabilities of a server'''
        with open(os.path.join(self.folderReception, FolderCommServer.CAPABILITYTEMPLATE.format(rid=rid))) as fin:
            return fin.read().strip().split()
    



