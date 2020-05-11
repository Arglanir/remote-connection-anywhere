'''
Contains all is needed for a communication to be established through a shared folder in an IMAP server.

Created on 21 avr. 2020

@author: Cedric
'''
from remoteconanywhere.communication import CommunicationSession, CommunicationServer, CommunicationClient
import os, logging, re, time
import imaplib

from email.parser import BytesParser
from email.mime.text import MIMEText
from email.policy import SMTP as POLICY
import base64, threading
from remoteconanywhere.cred import CredentialManager

LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))

# time before needing to restart connection
RESTART_AFTER = 3600 # seconds


# TODO: Imap with only one IMAP client that dispatch data to queues of sessions

class ImapCommSession(CommunicationSession):
    '''CommunicationSession that has its own connection to the server'''
    
    EXPECTED_SUBJECT_SENT = "{me}-{sid}-{other}-Message-{sent}th"
    # = "[{me}-{sid}-{other}] Message {received}"
    EXPECTED_SUBJECT_RECEIVED = EXPECTED_SUBJECT_SENT.replace(
        '{me}', '{temp}').replace(
        '{other}', '{me}').replace(
        '{temp}', '{other}').replace(
        '{sent}', '{received}') 
    
    PARSER = parser = BytesParser()
    
    SUFFIX_EMAIL='@remoteconanywhere.com'
    
    HEADER_SUBJECT = 'Subject'
    HEADER_FROM = 'From'
    HEADER_TO = 'To'
    
    APPENDUID_RX = re.compile(r"(?i)APPENDUID\s+(?P<uidstatus>\d+)\s+(?P<uid>\d+)")

    def subject2from(self, subject):
        return subject.split('-%s-' % self.sid)[0]
    
    def __init__(self, me, other, sid, imapclient):
        ''''@type imapclient: imaplib.IMAP4'''
        super().__init__(me, other, sid)
        #: :type imapclient: imaplib.IMAP4
        self.imapclient = imapclient
        self.cacheSubject = dict()
        self.lastSentMessageUid = None
        self.processed = set()
        self.imapLock = threading.RLock()
         
    
    def deleteLastMessage(self):
        self.sent -= 1
        if self.lastSentMessageUid is not None:
            self.deleteemail(self.lastMessageUid)
    
    def sendUnit(self, data):
        '''Send some data'''
        mime = MIMEText(self.data2payload(data))
        subject = self.EXPECTED_SUBJECT_SENT.format(**self.__dict__)
        mime[self.HEADER_SUBJECT] = subject
        mime[self.HEADER_FROM] = self.imapclient.forceHeaderFrom if self.imapclient.forceHeaderFrom else self.me + self.SUFFIX_EMAIL
        mime[self.HEADER_TO] = self.imapclient.forceHeaderTo if self.imapclient.forceHeaderTo else self.other + self.SUFFIX_EMAIL
        
        maildata = mime.as_bytes(POLICY)
        # test parsing:
        self.PARSER.parsebytes(maildata) # FIXME: remove me
        
        LOGGER.debug("Mail data of size %s to send: %s", len(maildata), "not displayable" if len(maildata) > 2000 else maildata)
        with self.imapLock:
            typ, response = self.imapclient.append(self.imapclient.forceMailbox, None, None, maildata)
        LOGGER.debug("Response from imap server to append: %s %r", typ, response)
        if typ != 'OK':
            LOGGER.warning("Seemed to not being able to send data: %r", maildata)
            raise ValueError("%s" % response)
        if "APPENDUID" in response[0].upper().decode():
            m = self.APPENDUID_RX.search(response[0].decode())
            if m:
                self.lastSentMessageUid = m.group("uid")
        LOGGER.debug("Sent data %s: (uid: %s)", "of size %s " % len(data) if len(data) > 50 else data, self.lastSentMessageUid)
        self.sent += 1
        
        # test if e-mail possible to be fetched:
        #mail = self.receiveEmail(self.lastSentMessageUid, False)
        #if mail is None:
        #    LOGGER.warn("E-mail cannot be retreived")
        #else:
        #    LOGGER.debug("Verification of sent e-mail: %s", self.payload2data(mail.get_payload()))

    
    def payload2data(self, payload):
        return base64.b64decode(payload)

    def data2payload(self, data):
        return base64.b64encode(data).decode('utf-8')
    
        
    def deleteemail(self, uid):
        """Delete an used e-mail from the server"""
        LOGGER.debug("Delete e-mail uid %s", uid)
        with self.imapLock:
            _typ, _resp = self.imapclient.uid('store', uid, r'+FLAGS.SILENT \Deleted')
            self.imapclient.expunge()
    
    @classmethod
    def extractEmailContentFromResponseHelper(cls, response):
        if isinstance(response, (list, tuple)):
            for portion in response:
                yield from cls.extractEmailContentFromResponseHelper(portion)
        if isinstance(response, (bytes, bytearray)):
            if b'Content-Type:' in response:
                yield response

    @classmethod
    def extractEmailContentFromResponse(cls, response):
        for found in cls.extractEmailContentFromResponseHelper(response):
            return found
        LOGGER.warning("Unable to find a suitable Content-Type: in %r", response)
        # any parsing will crash anyway, what should I return?
        raise ValueError("No content type in %r" % response)
        
    @property
    def nextSubjectToReceive(self):
        return self.EXPECTED_SUBJECT_RECEIVED.format(**self.__dict__)
    
    def checkIfDataAvailable(self):
        '''Returns True if a new chunk is available, False otherwise'''
        #: :type client: imaplib.IMAP4
        client = self.imapclient
        subject = self.nextSubjectToReceive
        if subject in self.cacheSubject:
            return True# = uidstofetch
        othersearch = ["HEADER", "Subject", subject, "NOT DELETED"
                       ]
        LOGGER.debug("Searching for emails that contains %s", othersearch)
        with self.imapLock:
            try:
                _typ, uids = client.uid('search', *othersearch)
            except Exception as e:
                LOGGER.warning("While checking for e-mail, got error: %s", e)
                uids = None
        if not uids or not uids[0]:
            LOGGER.debug("Nothing found.")
            return False
        uidstofetch = uids[0].decode().split()
        
        if len(uidstofetch) > 1:
            LOGGER.warning("More than one e-mail correspond to the search")
        
        self.cacheSubject[subject] = uidstofetch
        
        return True
    
    def discover(self, onlyOne=False):
        '''@return a list of [('other', b'data')]'''
        toreturn = []
        #: :type client: imaplib.IMAP4
        client = self.imapclient
        
        uptime = time.time() - client.startingtime
        LOGGER.debug("Uptime of connection sid=%s: %s", self.sid, uptime)
        if uptime > RESTART_AFTER:
            LOGGER.info("Reconnection after %s hour", RESTART_AFTER/3600)
            self.imapclient = client = client.renew()
        
        for delete, subjectbefore, subjectafter in [
            [True] + self.nextSubjectToReceive.split(self.other),
            [False] + self.EXPECTED_SUBJECT_SENT.format(**self.__dict__).split(self.me)]:
            search = ['NOT DELETED']
            if len(subjectbefore) > 2:
                search += ["HEADER", "Subject", subjectbefore]
            if len(subjectafter) > 2:
                search += ["HEADER", "Subject", subjectafter]
            LOGGER.debug("Searching for emails that contains %s", search)
            with self.imapLock:
                _typ, uids = client.uid('search', *search)
            if not uids[0]:
                LOGGER.debug("Nothing found.")
                continue
            uidstofetch = uids[0].decode().split()
            
            LOGGER.debug("%s corresponding e-mail found!", len(uidstofetch))
            for uid in uidstofetch:
                if uid in self.processed:
                    continue
                if not delete:
                    self.processed.add(uid)
                # read it, delete it
                message = self.receiveEmail(uid, delete)
                
                subject = message['Subject']
                data = self.payload2data(message.get_payload())
                toreturn.append((self.subject2from(subject), data))
                if onlyOne:
                    return toreturn
        LOGGER.info("Discovery loop found %s data", len(toreturn))
        return toreturn
    
    
    def receiveRawChunk(self):
        '''Receives some data (one chunk)
        @return: None if no more data available, a bytes if data available (possibly empty)'''
        if self.closed:
            return None
        if not self.checkIfDataAvailable():
            return b''
        subject = self.nextSubjectToReceive
        uidstofetch = self.cacheSubject[subject]
        del self.cacheSubject[subject]
        
        uid = uidstofetch[0]
        self.received += 1
        return self.receiveEmailAsData(uid)

    def receiveEmail(self, uid, delete=True):
        # fetch e-mail
        with self.imapLock:
            typ, resp = self.imapclient.uid('fetch', uid, '(RFC822)')
        LOGGER.debug("Fetch response: %s %r", typ, resp)
        if delete:
            self.deleteemail(uid)
        return self.PARSER.parsebytes(self.extractEmailContentFromResponse(resp))
    
    def receiveEmailAsData(self, uid, delete=True):
        message = self.receiveEmail(uid, delete)
        
        # read payload
        text = message.get_payload()
        
        # decoding
        data = self.payload2data(text)
        LOGGER.debug("Received data: %s", len(data) if len(data) > 50 else data)
        
        # remember to increase received!
        return data
    
    def close(self, silently=False):
        CommunicationSession.close(self, silently=silently)
        with self.imapLock:
            self.imapclient.close()
            self.imapclient.logout()
        


def createImapClient(hostname, port=None, ssl=True, tls=False, credmanager=CredentialManager(), folder=None, login=None):
    clazz = imaplib.IMAP4
    if ssl:
        clazz = imaplib.IMAP4_SSL
        if port is None:
            port = imaplib.IMAP4_SSL_PORT
    if port is None:
        port = imaplib.IMAP4_PORT
    LOGGER.info("Creating connection to %s:%s", hostname, port)
    firstconnection = True
    while True:
        client = clazz(hostname, port)
        if firstconnection:
            imapcapabilities = client.capability()[1][0].decode().upper().split()
            LOGGER.info("Connected to %s:%s with capabilities: %s", hostname, port, " ".join(imapcapabilities))
        
        if tls and "STARTTLS" in imapcapabilities:
            client.starttls()
        
        login, password = credmanager.getcredentials(hostname, login=login)
        
        # login
        try:
            client.login(login, password)
            break
        except client.error as e:
            LOGGER.warning("Impossible to connect: %s", e)
        # bad connection
        login, password = credmanager.badcredentials(hostname, login=login)
        # restart connection
        client.shutdown()
    
    if folder:
        try:
            resp = client.select(folder)
            LOGGER.debug("SELECT %s response: %s", folder, resp)
            if resp[0] == 'NO':
                raise client.error
        except client.error:
            LOGGER.warning("Creating mailbox %s", folder)
            client.create(folder)
            client.select(folder)
    else:
        client.select()
    
    LOGGER.info("Connected to %s as %s in folder %s", hostname, login, folder)
    
    # specific for our use: keep header and mailbox, and creation time
    client.forceHeaderFrom = None
    client.forceHeaderTo = None
    client.forceMailbox = folder
    client.login = login
    client.startingtime = time.time()
    
    def renew():
        client.close()
        client.logout()
        newclient = createImapClient(hostname, port, ssl, tls, credmanager, folder, login)
        return newclient
    
    client.renew = renew
    
    return client


class Imap4CommServer(CommunicationServer):
    
    SUBJECT_CAPABILITY = "Capabilities-{rid}-K"
    
    def subjectToRid(self, subject):
        ind = self.SUBJECT_CAPABILITY.index('{rid}')
        return subject[ind:-2]
    
    def __init__(self, rid, clientfactory, share=False):
        '''Initializes a server'''
        self.clientfactory = clientfactory
        #: :type currentclient: imaplib.IMAP4
        self.currentclient = None
        
        self.share = share
        super().__init__(rid)
    
    @property
    def imapclient(self):
        # restart client after 1 hour
        if self.currentclient is not None:
            uptime = time.time() - self.currentclient.startingtime
            LOGGER.debug("Uptime of server connection: %s", uptime)
            if uptime > RESTART_AFTER:
                LOGGER.info("Reconnection after %s hour", RESTART_AFTER/3600)
                self.currentclient.close()
                self.currentclient.logout()
                self.currentclient = None
        
        # test connection
        try:
            self.currentclient.noop()
        except:
            LOGGER.debug("Initializing a new connection")
            # new connection
            self.currentclient = self.clientfactory()
            
        return self.currentclient
    
    def createSession(self, cid, rid, sid):
        return ImapCommSession(rid, cid, sid, self.currentclient if self.share else self.clientfactory())
    
    
    def removeCapabilities(self, shouldexist=False):
        subject = self.SUBJECT_CAPABILITY.format(**self.__dict__)
        _typ, uids = self.imapclient.uid('search', 'NOT DELETED', 'HEADER', 'Subject', subject)
        if not uids[0]:
            # nothing to do
            if shouldexist:
                LOGGER.warn("Capability e-mail does not exist.")
            return
        if not shouldexist:
            LOGGER.warn("Capability e-mail already exists.")
        else:
            LOGGER.info("Removing capability e-mail %s", uids[0].decode())
        uidstofetch = uids[0].decode().split()
        client = self.imapclient
        for uid in uidstofetch:
            _typ, _resp = client.uid('store', uid, r'+FLAGS.SILENT \Deleted')
        client.expunge()
    
    def cleanUp(self):
        '''Cleans the shared space from older runs'''
        LOGGER.warn("Cleaning up shared space...")
        client = self.imapclient
        _typ, uids = client.uid('search', 'NOT DELETED')
        if not uids[0]:
            # nothing to do
            LOGGER.info("Folder already cleaned!")
            return
        uidstofetch = uids[0].decode().split()
        responses = set()
        for uid in uidstofetch:
            typ, _resp = client.uid('store', uid, r'+FLAGS.SILENT \Deleted')
            responses.add(typ)
        LOGGER.info("Cleaned %s e-mails: %s", len(uidstofetch), responses)
        client.expunge()
    
    def showCapabilities(self):
        '''Show the capabilities (and that I'm alive)'''
        towrite = ""
        for capa in self.capabilities:
            towrite += capa
            towrite += "\n"
        LOGGER.info("Indicating capabilities of %s: %s bytes (%s capabilities)",
                    self.rid, len(towrite), len(self.capabilities))
        
        # first: remove existing e-mail if exist, then store
        subject = self.SUBJECT_CAPABILITY.format(**self.__dict__)
        self.removeCapabilities()
        
        mime = MIMEText(towrite)
        mime[ImapCommSession.HEADER_SUBJECT] = subject
        mime[ImapCommSession.HEADER_FROM] = self.imapclient.forceHeaderFrom if self.imapclient.forceHeaderFrom else self.rid + ImapCommSession.SUFFIX_EMAIL
        mime[ImapCommSession.HEADER_TO] = self.imapclient.forceHeaderTo if self.imapclient.forceHeaderTo else self.rid + ImapCommSession.SUFFIX_EMAIL
        
        maildata = mime.as_bytes(POLICY)
        
        response = self.imapclient.append(self.imapclient.forceMailbox, None, None, maildata)
        LOGGER.debug("Response to append e-mail for capability: %r", response)
    
    def stop(self):
        LOGGER.info("Stopping server %s", self.rid)
        super().stop()
        # remove capabilities e-mail
        self.removeCapabilities()
        if self.currentclient is not None:
            self.currentclient.close()
            self.currentclient.logout()


class Imap4CommClient(CommunicationClient):

    def __init__(self, cid, clientfactory, share=False):
        self.clientfactory = clientfactory
        self.currentclient = None
        self.share = share # TODO: use me?
        super().__init__(cid)

    
    @property
    def imapclient(self):
        # restart client after 1 hour
        if self.currentclient is not None:
            uptime = time.time() - self.currentclient.startingtime
            LOGGER.debug("Uptime of client connection: %s", uptime)
            if uptime > RESTART_AFTER:
                LOGGER.info("Reconnection after %s hour", RESTART_AFTER/3600)
                self.currentclient.close()
                self.currentclient.logout()
                self.currentclient = None
        
        try:
            self.currentclient.noop()
        except Exception as e:
            LOGGER.debug("Initializing a new connection because %s", e)
            # new connection
            self.currentclient = self.clientfactory()
        return self.currentclient


    def createSession(self, cid, rid, sid):
        return ImapCommSession(cid, rid, sid, self.clientfactory())
    
    def listServers(self):
        '''List the servers rid'''
        # TODO: do it
        toreturn = []
        subject = Imap4CommServer.SUBJECT_CAPABILITY.split('{rid}')[0]
        _typ, uids = self.imapclient.uid('search', 'NOT DELETED', 'HEADER', 'Subject', subject)
        if not uids[0]:
            # nothing to do
            LOGGER.warn("No server is registered")
            return toreturn
        uidstofetch = uids[0].decode().split()
        client = self.currentclient
        for uid in uidstofetch:
            typ, resp = client.uid('fetch', uid, '(RFC822)')
            LOGGER.debug("Fetching capability email %s for name: %s %r", uid, typ, resp)
            message = ImapCommSession.PARSER.parsebytes(ImapCommSession.extractEmailContentFromResponse(resp))
            subject = message[ImapCommSession.HEADER_SUBJECT]
            rid = Imap4CommServer.subjectToRid(Imap4CommServer, subject)
            toreturn.append(rid)
        return toreturn
    
    def capabilities(self, rid):
        '''Check the capabilities of a server'''
        subject = Imap4CommServer.SUBJECT_CAPABILITY.format(rid=rid)
        _typ, uids = self.imapclient.uid('search', 'NOT DELETED', 'HEADER', 'Subject', subject)
        if not uids[0]:
            # nothing to do
            LOGGER.warn("No server named %s is registered", rid)
            return []
        uidstofetch = uids[0].decode().split()
        client = self.currentclient
        if len(uidstofetch) > 1:
            LOGGER.warning("More than one capability e-mail for rid %s: %s", rid, uidstofetch)
        toreturn = set()
        for uid in uidstofetch:
            typ, resp = client.uid('fetch', uid, '(RFC822)')
            LOGGER.debug("Fetching capability email %s (rid %s) for capabilities: %s %r", uid, rid, typ, resp)
            message = ImapCommSession.PARSER.parsebytes(ImapCommSession.extractEmailContentFromResponse(resp))
            #subject = message[ImapCommSession.HEADER_SUBJECT]
            #rid = Imap4CommServer.subjectToRid(Imap4CommServer, subject)
            toreturn.update(message.get_payload().split())
        return list(toreturn)
    
    
