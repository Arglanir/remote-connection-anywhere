'''
Created on 1 avr. 2020

@author: Cedric
'''

import os
import argparse
import re
import logging
import pickle
import time
import fnmatch
import threading
import queue

LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))


'''
What is a communication layer?
A way to transfer some data from one endpoint to another

It must be symmetric (data must be able to be transfered in both directions)

Servers register a special chunk listing their capabilities.

A "client" can "open a session" with one "capability"

Communication is bidirectionnal. (Client can send data, and server can send data)
At the end, the client sends to the server an end signal, the server can stop the session.

For the communication to happen:
- The client must be known (cid)
- The server/receiver has a name also (rid)
- Unique session (sid)

Then in order to pass big chucks of data:
- increasing number of messages

Special messages:
- client can send a message "list capabilities" to all servers (*), which can answer
'''

class CommunicationClient:
    '''Top class of a client'''
    METADATA = 'cid rid sid'.split()
    MESSAGES = 'capabilities data open stop report'.split()
    SPECIAL_MESSAGE_START_SESSION = b'MessageOutsideCommunication:PleaseStartASession:'
    
    def __init__(self, cid):
        self.cid = cid
    
    def createSession(self, cid, rid, sid):
        raise NotImplementedError
    
    def listServers(self):
        '''List the servers rid'''
        return []
    
    def capabilities(self, rid):
        '''Check the capabilities of a server'''
        return []
    
    def openSession(self, rid, service):
        '''Starts a session'''
        nosession = self.createSession(self.cid, rid, 0)
        nosession.send(CommunicationClient.SPECIAL_MESSAGE_START_SESSION + service.encode('utf-8'))
        while not nosession.checkIfDataAvailable():
            time.sleep(0.01)
        #nosession.deleteLastMessage()
        chunk = nosession.receiveChunk()
        sid = int(chunk)
        session = self.createSession(self.cid, rid, sid)
        return session



class CommunicationServer:
    '''Top class of a server'''
    METADATA = 'cid rid sid'.split()
    MESSAGES = 'mycapabilities data open stop myreport'.split()
    SPECIAL_MESSAGE_STOP_SERVER = b'MessageOutsideSession:StopServer'
    GENERIC_SPECIAL_MESSAGE = b'GenericMessageFor:' # + server / action + ":" + method + ":" arguments
    SPECIAL_MESSAGE_ERROR = b'Error:'
    
    def __init__(self, rid):
        '''Initializes a server'''
        self.rid = rid
        self.capabilities = dict()
        self.nextsessionid = 1
        self.stopped = False
        self.openedsessions = set()
    
    def registerCapability(self, server):
        self.capabilities[server.capability] = server
    
    def createSession(self, cid, rid, sid):
        raise NotImplementedError
    
    def checkForNoSessionMessages(self, onlyOne=False):
        '''Returns a list of [('cid', b'data')]'''
        nosession = self.createSession('ANY', self.rid, 0)
        return nosession.discover(onlyOne)
        
    def loopForNoSessionMessages(self):
        '''Wait for a connection to happen, then return a CommunicationSession'''
        while not self.stopped:
            toprocess = self.checkForNoSessionMessages()
            for onecomm in toprocess:
                self.handleNoSessionMessage(*onecomm)
                if onecomm[1] == self.SPECIAL_MESSAGE_STOP_SERVER:
                    break
            time.sleep(0.01)
    
    def stop(self, keepcurrentsessions=False):
        '''Stops the server, and close current sessions'''
        if not keepcurrentsessions:
            for session in list(self.openedsessions):
                session.close()
        self.stopped = True
    
    def handleNoSessionMessage(self, cid, data):
        '''Processes one session message'''
        if data.startswith(CommunicationClient.SPECIAL_MESSAGE_START_SESSION):
            service = data[len(CommunicationClient.SPECIAL_MESSAGE_START_SESSION):].decode('utf-8')
            messagetosend = str(self.nextsessionid).encode('utf-8')
            error = False
            if not service in self.capabilities:
                error = True
                messagetosend = self.SPECIAL_MESSAGE_ERROR + b'ServiceNotKnown:' + service
            nosession = self.createSession(cid, self.rid, 0)
            nosession.send(messagetosend)
            if not error:
                self.capabilities[service].start(self.createSession(cid, self.rid, self.nextsessionid))
            self.nextsessionid += 1
            # protection against file not removed yet
            #time.sleep(1)
        elif data.startswith(self.GENERIC_SPECIAL_MESSAGE):
            args = data.split(data[-1:])
            on = self if args[1] == b'server' else self.capabilities.get(args[1].decode('utf-8'))
            meth = args[2].decode('utf-8')
            argsmeth = [k.decode('utf-8') for k in args[3:]]
            try:
                toreturn = getattr(on, meth)(*argsmeth)
            except Exception as e:
                toreturn = self.SPECIAL_MESSAGE_ERROR + b'Error while calling ' + args[1] + b'.' + meth + b":" + str(e).encode('utf-8')
            nosession = self.createSession(cid, self.rid, 0)
            nosession.send(toreturn)
            # protection against file not removed yet
            #time.sleep(1)
            
    def showCapabilities(self):
        '''Show the capabilities'''
    
    def serveForever(self):
        self.showCapabilities()
        self.loopForNoSessionMessages()

class CommunicationSession:
    '''A CommunicationSession is something that can send/received data'''
    def __init__(self, me, other, sid):
        self.me = me
        self.other = other
        self.sid = sid
        self.sent = 0
        self.received = 0
        self.dataSent = 0
        self.maxdatalength = 500000
        self.cache = None
        self.cacheIndex = None
        self.cacheUpdateTime = 0.010
        self.closed = False
        self.data_to_close_session = b'MessageInCommunication:PleaseCloseTheSession'
        self.sendingLock = threading.RLock() # multiple threads can send()
        # self.receivingLock = threading.RLock() not used for the moment, only one thread must read

    
    def send(self, data):
        '''Send data, that can be split if too big'''
        with self.sendingLock:
            n = len(data)
            LOGGER.debug('Sending %s bytes from %s to %s (session %s msg %s)', n, self.me, self.other, self.sid, self.sent)
            if n > self.maxdatalength:
                m, k = divmod(n, self.maxdatalength)
                for i in range(m):
                    self.sendUnit(data[i*self.maxdatalength:(i+1)*self.maxdatalength])
                if k:
                    self.sendUnit(data[m*self.maxdatalength:])
            else:
                self.sendUnit(data)
            self.dataSent += n
            if data == self.data_to_close_session:
                self.closed = True
    
    def close(self):
        '''Close the session'''
        if not self.closed:
            if self.sid == 0 or self.sid == '0':
                self.closed = True
                # send nothing
            else:
                self.send(self.data_to_close_session)
    
    # Context manager
    def __enter__(self):
        return self
    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        self.close()
        return False
    
    
    def deleteLastMessage(self):
        pass
    
    def sendUnit(self, data):
        '''Send some data'''
        # implement me!
    
    def checkIfDataAvailable(self):
        '''Returns True if a new chunk is available, False otherwise'''
        return False
    
    def discover(self, onlyOne=False):
        '''@return a list of [('other', b'data')]'''
        return []
    
    
    def receiveRawChunk(self):
        '''Receives some data (one chunk)
        @return: None if no more data available, a bytes if data available (possibly empty)'''
        # remember to increase received!
        return b''
    
    
    def receiveChunk(self):
        '''Receives some data (one chunk)
        @return: None if no more data available, a bytes if data available (possibly empty)'''
        if self.closed:
            return None
        toreturn = self.receiveRawChunk()
        if toreturn:
            LOGGER.debug("%s received raw chunk from %s (session %s) of size %s", self.me, self.other, self.sid, len(toreturn))
        if toreturn == self.data_to_close_session:
            # close the session
            toreturn = None
            self.closed = True
        return toreturn
    
    def receiveOneByte(self, timeout=None):
        '''Receives one byte, or None if timeout is passed.'''
        check = self.checkIfOneByteAvailable(timeout)
        if not check:
            # connection closed or no byte to return (timeout passed)
            return None
        index = self.cacheIndex
        self.cacheIndex += 1
        return self.cache[index:index+1]
    
    def checkIfOneByteAvailable(self, timeout=None):
        '''@return True if one byte is available, False if no byte is available, None if session is closed'''
        if self.cache is None or self.cacheIndex >= len(self.cache):
            self.cache = None
            end = timeout + time.time() if timeout else None
            while not self.cache and (end is None or end > time.time()):
                self.cache = self.receiveChunk()
                if self.cache is None:
                    # no more data available, closed
                    return None
                if not self.cache:
                    time.sleep(self.cacheUpdateTime)
            self.cacheIndex = 0
        return self.cache and len(self.cache) > self.cacheIndex
        

class ActionServer:
    '''Abstract class that describes an action'''
    def __init__(self, capability):
        self.capability = capability
    
    def start(self, session):
        '''Given a session, able to communicate / start the application'''
        


class QueueCommunicationSession(CommunicationSession):
    '''This communication session allows handling queues in memory, mainly for tests'''
    
    def __init__(self, me='me', other='other', sid=1):
        CommunicationSession.__init__(self, me, other, sid)
        self.recqueue = queue.Queue()
        self.sentqueue = queue.Queue()
    
    def deleteLastMessage(self):
        pass
    
    def sendUnit(self, data):
        '''Send some data'''
        self.sentqueue.put(data)
    
    def checkIfDataAvailable(self):
        '''Returns True if a new chunk is available, False otherwise'''
        return not self.recqueue.empty()
    
    def discover(self, onlyOne=False):
        '''@return a list of [('other', b'data')]'''
        return []
    
    def receiveRawChunk(self):
        '''Receives some data (one chunk)
        @return: None if no more data available, a bytes if data available (possibly empty)'''
        # remember to increase received!
        if self.closed:
            return None
        try:
            return self.recqueue.get(block=False)
        except queue.Empty:
            return b''
    
    def memoryPutSomeData(self, data):
        self.recqueue.put(data)

    def memoryGetSentData(self):
        try:
            return self.sentqueue.get(block=False)
        except queue.Empty:
            return None
    
    def inexorablyLinkQueue(self, other):
        '''Creates a thread that copies what is in one queue to another'''
        self.other = other.me
        other.other = self.me
        def torun():
            infinite = True
            while (infinite and not self.closed) or not self.sentqueue.empty() or not other.sentqueue.empty():
                for a,b in ((self, other), (other, self)):
                    try:
                        data = a.sentqueue.get(timeout=0.001)
                        b.recqueue.put(data)
                        if data == self.data_to_close_session:
                            infinite = False
                    except queue.Empty:
                        pass
        threading.Thread(target=torun, name='LinkedQueueCommSession-%s-%s' % (self.me, other.me), daemon=True).start()



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
        super().__init__(rid)
        if folderEmission is None:
            folderEmission = folderReception
        self.folderReception = folderReception
        self.folderEmission = folderEmission
        for dire in (folderEmission, folderReception):
            if not os.path.exists(dire):
                os.makedirs(dire)
    
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
    













class CommunicationChannel:
    """Channel of communication"""
    METADATA = 'sid orig session nreq nmail last'.split()
    LAST_LAST = 'last'
    LAST_NOTLAST = '-'
    
    SESSION_NEW = '-'
    
    # flag to indicate whether all methods are implemented
    USABLE = False
    
    def issymmetric(self):
        """Indicates if this CommunicationChannel is symmetric. It means that after a senddata,
        the sent data can be retrieve by the same object using checkfordata.
        It will be False for Imap/SmtpConnection"""
        return True
    
    def senddata(self, data, **kwargs):
        """Send the data to the provided arguments
        @return: if symmetric, return the uid of the message"""
        raise NotImplementedError
    
    def checkkwargs(self, kwargs, globalcheck=None, **kwargsexpected):
        """Checks a kwargs for expected values.
        Called in checkfordata (for new found data or cache)
        @return: True if kwargs corresponds, False otherwise"""
        for k in self.METADATA:
            v = kwargsexpected.get(k)
            if v is None:
                continue
            if isinstance(v, str) and kwargs[k] != v:
                return False
            if isinstance(v, int) and kwargs[k] != str(v):
                return False
            if callable(v) and not callable(kwargs[k]):
                return False
        if callable(globalcheck) and not globalcheck(kwargs):
            return False
        return True
    
    def checkfordata(self, globalcheck=None, **kwargsexpected):
        """Wait for data that corresponds to the provided checks.
        May store the uids => kwargs in a cache (must be emptied in deletedata)
        @return: the list of corresponding uids (may be empty)"""
        raise NotImplementedError
    
    def retrievedata(self, uid, deleteafteruse=True):
        """Retrieve some data.
        @param uid: the uid as returned by checkfordata
        @return a tuple (kwargs, data)"""
        raise NotImplementedError

    def deletedata(self, uid):
        """Delete some data given the uid.
        @param uid: the uid as returned by checkfordata"""
        raise NotImplementedError

class FolderCommunicationChannel(CommunicationChannel):
    """Channel of communication using a folder
    uids are the file names directly"""
    # flag to indicate that all methods are implemented
    USABLE = True
    FILENAME = 'RemoteCon,i={sid},r={orig},e={session},r={nreq},m={nmail},a={last},.bin'
    FILENAME_RX = re.compile(re.sub(r"{(\w+)\}", r"(?P<\1>[a-zA-Z0-9*_.-]+)", FILENAME).replace(' ', r'\s+').replace(',', r',\s*')+"$")
    #GROUP_PATTERN = ",{group[1]}={value},"
    TEMPPATTERN = ".{}.temp"
    
    def __init__(self, hostname=None, credmanager=None, login=None, password=None):
        folder = self.folder = hostname
        if not os.path.isdir(folder):
            raise argparse.ArgumentError('The hostname must be an existing folder')
    
    def issymmetric(self):
        """Indicates if this CommunicationChannel is symmetric. It means that after a senddata,
        the sent data can be retrieve by the same object using checkfordata.
        It will be False for Imap/SmtpConnection"""
        return True
    
    def senddata(self, data, **kwargs):
        """Send the data to the provided arguments
        @return: if symmetric, return the uid of the message"""
        filename = self.FILENAME.format(**kwargs)
        LOGGER.debug("Writing file %s", filename)
        destfilename = os.path.join(self.folder, filename)
        tempfilename = os.path.join(self.folder, self.TEMPPATTERN.format(filename))
        with open(tempfilename, 'wb') as fout:
            pickle.dump(data, fout)
        os.rename(tempfilename, destfilename)
        return filename

    def checkfordata(self, globalcheck=None, **kwargsexpected):
        """Wait for data that corresponds to the provided checks.
        May store the uids => kwargs in a cache (must be emptied in deletedata)
        @return: the list of corresponding uids (may be empty)"""
        foundfiles = []
        for fil in os.listdir(self.folder):
            m = self.FILENAME_RX.match(fil)
            if not m: continue
            kwargs = m.groupdict()
            if self.checkkwargs(kwargs, globalcheck, **kwargsexpected):
                foundfiles.append(fil)
        LOGGER.debug("%s file(s) match", len(foundfiles))
        return foundfiles
    
    def retrievedata(self, uid, deleteafteruse=True):
        """Retrieve some data.
        @param uid: the uid as returned by checkfordata
        @return a tuple (kwargs, data)"""
        LOGGER.debug("Retrieving file %s", uid)
        kwargs = self.FILENAME_RX.match(uid).groupdict()
        with open(os.path.join(self.folder, uid), 'rb') as fin:
            data = pickle.load(fin)
        if deleteafteruse:
            self.deletedata(uid)
        return kwargs, data

    def deletedata(self, uid):
        """Delete some data given the uid.
        @param uid: the uid as returned by checkfordata"""
        LOGGER.debug("Removing file %s", uid)
        os.remove(os.path.join(self.folder, uid))

