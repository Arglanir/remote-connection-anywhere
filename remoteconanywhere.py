#!/usr/bin/env python3
# This script allows a client and a server to communicate through a proxy,
# like an e-mail server
import netrc
import imaplib
import subprocess
import threading
import re
import time
import datetime
import sys
import os
import json
import getpass
import zlib
import base64
import random
import argparse
import uuid, hashlib
from email.parser import BytesParser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import logging

LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))

# ##################################### CREDENTIALS

#         CCC RRR  EEEE DDD  EEEE N   N TTTTT III  AA  L    SSS                                                             
#        C    R  R E    D  D E    NN  N   T    I  A  A L   S                                                                    
#        C    RRR  EEE  D  D EEE  N N N   T    I  AAAA L    SSS                                                                           
#        C    R R  E    D  D E    N  NN   T    I  A  A L       S                                                                 
#         CCC R  R EEEE DDD  EEEE N   N   T   III A  A LLLL SSS                                                                           

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
        inputlogin = input("".join(("Login", "" if not login else " [default: %s]" % login, ": "))) or login
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
                LOGGER.warn("Error loading file %s: %r", self.file, e)
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

def testMyCredManager():
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    alphabet = alphabet + alphabet.upper()+"0123456789'\"-_({)]=)"
    for i in range(20):
        testpassword = "".join(random.sample(alphabet, random.randrange(10,20)))
        shadedeshade = MyCredManager.deshadepassword(MyCredManager.shadepassword(testpassword))
        assert testpassword == shadedeshade, testpassword + "!=" + shadedeshade
        assert testpassword != MyCredManager.shadepassword(testpassword), testpassword + "==" + MyCredManager.shadepassword(testpassword)
testMyCredManager()

# list of credential managers
CREDENTIAL_MANAGERS = {
    "NETRC":NetRcCredManager,
    "DEFAULT": MyCredManager,
    "ASK": CredentialManager
}

# ######################################### Command/responses

class Command:
    def __init__(self, msg, data=None):
        self.msg = msg
        self.data = data

class Response:
    returncode = None
    stdout = None
    stderr = None
    start = None
    end = None
    def __repr__(self):
        return type(self).__name__ + repr(self.__dict__)

# ####################################### Base classes client / server

class ServerBase:
    def __init__(self, proxyaddr, credmanager, id):
        LOGGER.warn("Creating %s to %s with id=%s", type(self).__name__, proxyaddr, id)
        self.proxyaddr = proxyaddr
        self.credmanager = credmanager
        self.id = id

class ClientBase:
    """Base class for a client"""
    def __init__(self, proxyaddr, credmanager, id):
        LOGGER.warn("Creating %s to %s with id=%s", type(self).__name__, proxyaddr, id)
        self.proxyaddr = proxyaddr
        self.credmanager = credmanager
        self.id = id

    def discover(self, serverid=None):
        """Sends a special command in order to get all servers connected to the proxy.
        @return: list of (serverid, version, capabilities)"""
        raise NotImplementedError

    def connect(self, serverid):
        """Connects to the specified server
        (Note: it must behind the scene store the serverid, and a session token)"""
        raise NotImplementedError

    def send(self, command:Command, callbackstdout=None, callbackstderr=None)->Response:
        """Executes the given command on the given server.
        @param command: a command
        @param callbackstdout: callback called when some stdout arrives
        @param callbackstderr: callback called when some stderr arrives
        @return: the returned response object"""
        raise NotImplementedError

# ######################################## Responders

class Responder:
    """An executor of commands"""
    @staticmethod
    def readchannel(process, channel, destination, channelname):
        print("Listening to process {process.pid}'s {channelname}...".format(**locals()))
        while True:
            l = channel.readline()
            destination.append(l)
            process.poll()
            if process.returncode is not None:
                break
        print("End of listening to process {process.pid}'s {channelname}.".format(**locals()))

class BashResponder(Responder):
    """Executor of bash commands"""
    END_OF_PROGRAM = "@@@END_OF_PROGRAM_{}@@@CODE:$__code"

    TIME_BETWEEN_PEEK = 1 # time in seconds between interrogation of the process

    p = None
    def __init__(self):
        """Constructor"""
        if self.p is not None:
            # process already started : kill it
            self.p.kill()
        self.p = subprocess.Popen(["/bin/bash"], bufsize=0, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.out = []
        self.err = []
        self.nbc = 0
        for args in ((self.p.stdout, self.out, "out"), (self.p.stderr, self.err, "err")):
            t = threading.Thread(target=self.readchannel, args=(self.p,)+args)
            t.daemon = True
            t.start()

    def ask(self, command, callbackstdout=lambda *s:None, callbackstderr=lambda *s:None):
        self.nbc += 1
        self.p.stdin.write(command.strip('\n').encode())
        resp = Response()
        resp.start = datetime.datetime.now()
        # empty stdout and stderr ?
        self.out[:] = []
        self.err[:] = []
        end_of_program_string = self.END_OF_PROGRAM.format(self.nbc)
        self.p.stdin.write('\n__code=$? ; echo "{}" ; (exit $__code)\n'.format(end_of_program_string).encode())
        rx = re.compile(end_of_program_string.replace("$__code", r"(?P<code>\d+)"))
        lastidxout, lastidxerr, returncode = 0, 0, None
        needtorestart = False
        while returncode is None:
            time.sleep(self.TIME_BETWEEN_PEEK)
            currentlenerr = len(self.err)
            currentlenout = len(self.out)
            if currentlenerr>lastidxerr: # some output received
                callbackstderr(b''.join(self.err[lastidxerr:currentlenerr]))
                lastidxerr = currentlenerr
            if currentlenout>lastidxout: # some output received
                callbackstdout(b''.join(self.out[lastidxout:currentlenout]))
                # check each new line if the end of program has been reached
                for i in range(lastidxout, currentlenout):
                    l = self.out[i]
                    m = rx.search(l.decode(errors='ignore'))
                    if m is not None:
                        # program is terminated !
                        returncode = int(m.group('code'))
                        del self.out[i]
                        break
                lastidxout = currentlenout
            self.p.poll()
            if self.p.returncode is not None:
                # bash program exited
                returncode = self.p.returncode
                print("bash exited with code", returncode)
                self.err.append("Bash exited with code {}".format(returncode).encode())
                needtorestart = True
                if not returncode:
                    returncode = 255
                break
        # terminate the call
        time.sleep(self.TIME_BETWEEN_PEEK)
        resp.returncode = returncode
        resp.stdout = b''.join(self.out)
        resp.stderr = b''.join(self.err)
        self.out[:] = []
        self.err[:] = []
        resp.end = datetime.datetime.now()
        # restart if needed then answers
        if needtorestart:
            self.__init__()
        return resp

    def __del__(self):
        if self.p is not None:
            self.p.kill()




    def close(self):
        self.p.kill()



# ###################################### IMAP Protocol

#       III M   M  AA  PPP 
#        I  MM MM A  A P  P
#        I  M M M AAAA PPP 
#        I  M   M A  A P   
#       III M   M A  A P   

class ImapCommon:
    EXPECTED_SUBJECT = "RemoteConnection"
    # sid: destination id
    # orig: origin id
    # session: # of server session (- when starting session)
    # nreq: # of request (incremental)
    # nmail: # of e-mail (incremental)
    # last: "-" if not last, "last" if last
    SUBJECT_PATTERN = EXPECTED_SUBJECT + r" sid{sid}, orig{orig}, session{session}, nreq{nreq}, nmail{nmail}, last{last},"
    SUBJECT_RX = re.compile(re.sub(r"{(\w+)\}", r"(?P<\1>[a-zA-Z0-9*_.-]+)", SUBJECT_PATTERN).replace(' ', r'\s+'))
    SUBJECT_GROUPS = 'sid orig session nreq nmail last'.split()
    SEARCH_SUBJECT_PATTERN = "{group}{value},"
    parser = BytesParser()
    
    ORIG_CLIENT = 'client'
    ORIG_SERVER = 'server'
    LAST_LAST = 'last'
    LAST_NOTLAST = '-'
    
    SESSION_NEW = '-'
    
    SEARCH_INTERVAL = 1

    def connect(self, hostname, credmanager, login=None, password=None):
        #LOGGER.debug("Connecting to %s", hostname)
        self.credmanager = credmanager
        self.conn = imaplib.IMAP4(hostname)
        self.conn.starttls()
        self.connlock = threading.RLock()
        if login is None and password is None:
            login, password = self.credmanager.getcredentials(hostname, login=login)
        while True:
            try:
                self.conn.login(login, password)
                break
            except self.conn.error as e:
                print("Error returned from server:", repr(e))
            login, password = self.credmanager.badcredentials(hostname, login=login)
            # restart connection
            self.conn.shutdown()
            self.conn = imaplib.IMAP4(hostname)
            self.conn.starttls()
        LOGGER.debug("Connected to %s as %s", hostname, login)
        self.conn.select()

    def email2mime(self, uid):
        """Read an e-mail from the IMAP server."""
        LOGGER.debug("Fetching e-mail uid %s", uid)
        typ, resp = self.conn.uid('fetch', uid, '(RFC822)')
        message = self.parser.parsebytes(resp[0][1])
        return message

    def deleteemail(self, uid):
        """Delete an used e-mail from the server"""
        LOGGER.debug("Delete e-mail uid %s", uid)
        with self.connlock:
            typ, resp = self.conn.uid('store', uid, r'+FLAGS.SILENT \Deleted')
            self.conn.expunge()

    def mime2email(self, mime):
        """Write an e-mail to the IMAP server."""
        data = mime.as_bytes()
        LOGGER.debug("Writing e-mail with subject %s size %s", mime['Subject'], len(data))
        with self.connlock:
            self.conn.append(None, None, None, data)
    
    @classmethod
    def parsesubject(cls, data):
        """Parse data for a subject
        @return the re.MATCH object of the subject"""
        toreturn = None
        if type(data) == bytes:
            # raw e-mail
            header = cls.parser.parsebytes(data)
            subject = header['Subject']
        elif type(data) == str:
            # direct subject
            subject = data
        elif hasattr(data, '__contains__') and 'Subject' in data:
            # parsed e-mail
            subject = data['Subject']
        toreturn = cls.SUBJECT_RX.match(subject)
        return toreturn

    def waitforemail(self, sid=None, orig=None, session=None, nreq=None, nmail=None, last=None,
                     globalcheck=None, deleteafteruse=True):
        """Wait for a specific email and return it.
        @param sid, orig, session, nreq, nmail, last: search criteria that can be a string or a function(criteria_value:str)->bool
        @param globalcheck: a function(mimeheader:Message, parsedsubject:re.MATCH) -> bool called after all checks are ok
        @return the first e-mail that corresponds to the criteria
        """
        othersearch = ["SUBJECT", self.EXPECTED_SUBJECT, "NOT DELETED"]
        for grp in self.SUBJECT_GROUPS:
            if type(locals()[grp]) is str:
                othersearch.append('SUBJECT')
                othersearch.append(self.SEARCH_SUBJECT_PATTERN.format(group=grp, value=locals()[grp]))
        found = None
        LOGGER.debug("Searching for emails that contains %s", othersearch)
        while not found:
            # searching e-mails
            with self.connlock:
                typ, uids = self.conn.uid('search', *othersearch)
            if not uids[0]:
                time.sleep(self.SEARCH_INTERVAL)
                continue
            # fetching them all
            LOGGER.info("Emails corresponding to %s found: %s", othersearch, uids[0].decode())
            with self.connlock:
                typ, responses = self.conn.uid('fetch', ",".join(uids[0].decode().split()), "(UID RFC822.HEADER)")
            LOGGER.debug("Fetched headers %s: %r", typ, responses)
            for response in responses:
                if type(response) is not tuple:
                    LOGGER.debug("Discarded response %s: %s", type(response), response)
                    continue
                # read response header
                msgnum, _, uid, _, hsize = response[0].decode().split()
                # hsize = int(hsize.replace('{','').replace('}'))
                sheader = response[1]
                header = self.parser.parsebytes(sheader)
                subject = header['Subject']
                LOGGER.debug("Checking email uid=%s msgnum=%s: %s", uid, msgnum, subject)               
                # parse the header
                m = self.SUBJECT_RX.match(subject)
                if not m:
                    LOGGER.warn("Unable to parse subject: %s", subject)
                    continue
                # tests the header
                corresponds = True
                for k, v in m.groupdict().items():
                    if locals()[k] is not None:
                        if callable(locals()[k]) and not locals()[k](v):
                            corresponds = False
                            LOGGER.info("Email uid %s does not meet awaited condition on %s", uid, k)
                            break
                if corresponds and globalcheck is not None:
                    corresponds = globalcheck(header, m)
                # stop if ok
                if corresponds:
                    found = uid
                    break
                if found: break
            if found: break
            time.sleep(self.SEARCH_INTERVAL)
        # fetch full e-mail
        parsedemail = self.email2mime(found)
        if deleteafteruse:
            self.deleteemail(found)
        return parsedemail


testm = ImapCommon.SUBJECT_RX.match(ImapCommon.SUBJECT_PATTERN.replace("{","").replace("}","---"))
assert testm
assert all(k+"---" == testm.group(k) for k in "sid orig session nreq nmail last".split())

class ServerSession:
    session = 0
    nreq = 0
    nreqserver = 0
    otherid = None
    nmail = 0
    last = True
    request = []

class ImapServer(ServerBase, ImapCommon):
    SEARCH_INTERVAL = 2 # in seconds
    SESSIONCLASS = ServerSession

    def __init__(self, hostname, credmanager, login=None, password=None, id=None):
        super().__init__(hostname, credmanager, id)
        self.connect(hostname, credmanager, login, password)
        self.sessions = {} # sessionid => store
        self.currentsessionid = 0
        self.t = threading.Thread(target=self.loop)
        self.t.start()

    def loop(self):
        while True:
            self.search()
            time.sleep(self.SEARCH_INTERVAL)

    def accept(self, mailheader, parsedsubject):
        session = parsedsubject.group('session')
        nreq = parsedsubject.group('nreq')
        nmail = parsedsubject.group('nmail')
        last = parsedsubject.group('last')
        if session == self.SESSION_NEW:
            # new session
            return True
        if session in self.sessions:
            sessobj = self.sessions[session]
            if sessobj.last and nreq == str(sessobj.nreq+1) and nmail == '0':
                # previous request was finished and we have a new request
                return True
            elif not sessobj.last and nreq == str(sessobj.nreq) and nmail == str(sessobj.nmail+1):
                # previous request was not finished and we have a next email
                return True
        # not an accepted e-mail
        return False

    def search(self):
        msg = self.waitforemail(sid=self.id, globalcheck=self.accept)
        parsedsubject = self.parsesubject(msg)
        orig = parsedsubject.group('orig')
        session = parsedsubject.group('session')
        nreq = parsedsubject.group('nreq')
        nmail = parsedsubject.group('nmail')
        last = parsedsubject.group('last')
        if session == '-':
            # new session
            self.currentsessionid += 1
            sessionobj = self.SESSIONCLASS()
            sessionobj.otherid = orig
            sessionobj.session = self.currentsessionid
            sessionobj.request = [msg]
            self.sessions[sessionobj.session] = sessionobj
            # TODO : what if first message is big ?
            return self.newsession(sessionobj, msg)
        if session in self.sessions:
            sessionobj = self.sessions[session]
            if sessionobj.last and nreq == str(sessionobj.nreq+1) and nmail == '0':
                # previous request was finished and we have a new request
                sessionobj.request = [msg]
                sessionobj.nreq = str(nreq)
                sessionobj.nmail = str(nmail)
                islast = sessionobj.last = last == self.LAST_LAST
                if islast:
                    return self.requestcomplete(sessionobj, msg)
                else:
                    return self.requestnotcomplete(sessionobj, msg)
            elif not sessionobj.last and nreq == str(sessionobj.nreq) and nmail == str(sessionobj.nmail+1):
                # previous request was not finished and we have a next email
                sessionobj.request.append(msg)
                sessionobj.nreq = int(nreq)
                sessionobj.nmail = int(nmail)
                last = sessionobj.last = last == self.LAST_LAST
                if islast:
                    return self.requestcomplete(sessionobj, *sessionobj.request)
                else:
                    return self.requestnotcomplete(sessionobj, *sessionobj.request)
        LOGGER.error("Should not have arrived here... %s", parsedsubject.groupdict())
    
    def newsession(self, sessionobj, msg, text='Proceed'):
        """New session requested."""
        returned = MIMEText(text)
        sessionobj.nreqserver += 1
        returned['Subject'] = self.SUBJECT_PATTERN.format(sid=sessionobj.otherid,
                                     orig=self.id, session=sessionobj.session,
                                     nreq=sessionobj.nreqserver, nmail=0, last=self.LAST_LAST)
        # send response to server
        self.mime2email(returned)

    def requestcomplete(self, sessionobj, *msgs):
        pass

    def requestnotcomplete(self, sessionobj, *msgs):
        pass


class ImapBashServer(ImapServer):
    """Server that executes bash commands."""
    def __init__(self, hostname, credmanager, login=None, password=None, id=None):
        ImapServer.__init__(self, hostname, credmanager, login, password, id)
    
    def newsession(self, sessionobj, msg):
        # create console
        sessionobj.console = BashResponder()
        # answer back
        super().newsession(sessionobj, msg)

    def requestcomplete(self, sessionobj, *msgs):
        if msgs[0].is_multipart():
            pass
        else:
            command = msgs[0].get_payload()
            sessionobj.console

class ImapClient(ClientBase, ImapCommon):
    SEARCH_INTERVAL = 5
    def __init__(self, hostname, credmanager, login=None, password=None, id=None):
        super().__init__(hostname, credmanager, id)
        self.connect(hostname, credmanager, login, password)
        self.t = threading.Thread(target=self.loop)
        self.t.start()
    def loop(self):
        while True:
            self.conn.noop()
            time.sleep(self.SEARCH_INTERVAL)
    def send(self, command:Command, callbackstdout=None, callbackstderr=None)->Response:
        """Executes the given command on the given server.
        @param command: a command
        @param callbackstdout: callback called when some stdout arrives
        @param callbackstderr: callback called when some stderr arrives
        @return: the returned response object"""
        msg = ""
        data = None
        if type(command) is str:
            msg = command
        elif hasattr(command, 'msg'):
            msg = command.msg
            if hasattr(command, 'data'):
                data = command.data
        if not data:
            message = MIMEText(msg)
            message['Subject'] = self.EXPECTED_SUBJECT

# ############################################## Socket server/client
#
#       III M   M  AA  PPP    SSS   OO   CCC K  K EEEE TTTTT      
#        I  MM MM A  A P  P  S     O  O C    K K  E      T       
#        I  M M M AAAA PPP    SSS  O  O C    KK   EEE    T                
#        I  M   M A  A P         S O  O C    K K  E      T            
#       III M   M A  A P      SSS   OO   CCC K  K EEEE   T                     

import socket

class ImapSocketCommon(ImapCommon):
    TEXT_EXPOSE_SOCKET = "Please expose port {port} on machine {host}"
    TEXT_STOP = "Please stop communication"
    RX_EXPOSE_SOCKET = re.compile(re.sub(r"{(\w+)\}", r"(?P<\1>[a-zA-Z0-9_.-]+)", TEXT_EXPOSE_SOCKET.replace(' ', r'\s+')))
    
    MAX_SIZE_DATA = 1000*1000
    
    def senddatatootherend(self, session, data, nreq, destinationid):
        # compress data
        zdata = zlib.compress(data)
        # check how it will be split (if needed)
        nbchunks = len(zdata)//self.MAX_SIZE_DATA + 1
        chunksize = len(zdata)//nbchunks+1
        nmail = -1
        for i in range(nbchunks):
            # send each chunk
            nmail += 1
            tosend = zdata[i*chunksize:(i+1)*chunksize]
            msg = MIMEApplication(tosend)
            msg['Subject'] = self.SUBJECT_PATTERN.format(sid=destinationid, orig=self.id, session=session,
                            nreq=nreq, nmail=nmail, last=ImapCommon.LAST_LAST if i == nbchunks-1 else ImapCommon.LAST_NOTLAST)
            self.mime2email(msg)
     
    
    def listentosocketandsendmail(self, conn, destinationid, session, nreqstart=0):
        #key = "{}:{}".format(serverid, session)
        nreq = nreqstart
        conn.setblocking(False)
        start = time.time()
        tosend = []
        def emptytosend():
            nonlocal nreq
            nreq += 1
            self.senddatatootherend(session, b''.join(tosend), nreq, destinationid=destinationid)
            tosend[:] = []
        while True:
            # receive some data
            try:
                data = conn.recv(4096)
            except BlockingIOError:
                # no data received, wait a little
                if tosend:
                    emptytosend()
                time.sleep(500)
                start = time.time()
                continue
            except (ConnectionResetError, OSError):
                # end of communication
                data = b''

            if data is not None and len(data) == 0:
                # communication terminated
                if tosend:
                    # send remaining data
                    emptytosend()
                # send indication to stop
                LOGGER.info("Session %s: End of communication")
                msg = MIMEText(self.TEXT_STOP)
                nreq += 1
                msg['Subject'] = self.SUBJECT_PATTERN.format(sid=destinationid, orig=self.id, session=session,
                            nreq=nreq, nmail=0, last=ImapCommon.LAST_LAST)
                self.mime2email(msg)
                # close connection
                conn.close()
                # stop thread
                return
            # append some data
            tosend.append(data)
            if time.time() - start > 1:
                # time to send a new message
                emptytosend()
                start = time.time()

class ImapSocketServer(ImapServer, ImapSocketCommon):
    """Server that forwards a port."""
    def __init__(self, hostname, credmanager, login=None, password=None, id=None):
        ImapServer.__init__(self, hostname, credmanager, login, password, id)

    def newsession(self, sessionobj, msg):
        # store info about the socket to display
        m = self.RX_EXPOSE_SOCKET.search(msg.get_payload())
        if m is None:
            return super().newsession(sessionobj, msg, 'Bad request')
        # open socket
        sessionobj.socketlocalport = m.group('host'), int(m.group('port'))
        LOGGER.info("Session %s: New connection to %s", sessionobj.session, sessionobj.socketlocalport)
        sessionobj.socket = socket.create_connection(sessionobj.socketlocalport)
        sessionobj.listeningsocketthread = threading.Thread(target=self.listeningtosocket, args=(sessionobj,))
        sessionobj.listeningsocketthread.start()
        # answer back
        return super().newsession(sessionobj, msg)

    def listeningtosocket(self, sessionobj):
        """Listener on socket, must be run in separate thread."""
        return self.listentosocketandsendmail(sessionobj.socket, sessionobj.otherid, sessionobj.session, sessionobj.nreqserver)

    def requestcomplete(self, sessionobj, *msgs):
        if any(msg.is_multipart() for msg in msgs):
            LOGGER.error("Received an unexpected multipart message.")
        elif len(msgs) == 1 and type(msgs[0].get_payload()) == str and self.TEXT_STOP in msgs[0].get_payload():
            # stop connection
            LOGGER.info("Session %s: Terminating", sessionobj.session)
            sessionobj.socket.close()
            msg = MIMEText("Socket closed.")
            sessionobj.nreqserver += 1
            msg['Subject'] = self.SUBJECT_PATTERN.format(sid=sessionobj.otherid, orig=self.id, session=sessionobj.session,
                            nreq=sessionobj.nreqserver, nmail=0, last=ImapCommon.LAST_LAST)
            self.mime2email(msg)
        else:
            # send message
            zdata = b''.join(msg.get_payload(decode=True) for msg in msgs)
            data = zlib.decompress(zdata)
            LOGGER.info("Session %s: Sending data %s bytes", sessionobj.session, len(data))
            sessionobj.socket.sendall(data)

class ImapSocketClientSession(ServerSession):
    def __init__(self, serverid, socketclient, address):
        self.otherid = serverid
        self.socket = socketclient
        self.address = address
        self.request = []

class ImapSocketClient(ClientBase, ImapSocketCommon):
    def __init__(self, hostname, credmanager, login=None, password=None, id=None):
        super().__init__(hostname, credmanager, id)
        self.connect(hostname, credmanager, login, password)
        self.sessions = {} # serverid+':'+sessionid => ImapSocketClientSession
        self.waitingthread = threading.Thread(target=self.loop)
        self.waitingthread.start()
    
    def loop(self):
        def checkifmessageforme(msg, m):
            key = "{}:{}".format(m.group('orig'), m.group('session'))
            if key not in self.sessions:
                return False
            sessionobj = self.sessions[key]
            nreq = int(m.group('nreq'))
            nmail = int(m.group('nmail'))
            if sessionobj.last and nmail == 0 and nreq == sessionobj.nreq + 1: 
                # last message is complete, waiting for nmail = 0 nreq = sessionobj.nreq+1
                return True
            if not sessionobj.last and nreq == sessionobj.nreq and nmail == sessionobj.nmail + 1:
                # next email for request
                return True
            return False
                
        # loop that dispatches messages to the sockets
        while True:
            msgforme = self.waitforemail(sid=self.id, orig=None, session=None, nreq=None, nmail=None, last=None,
                     globalcheck=checkifmessageforme)
            m = self.parsesubject(msgforme)
            key = "{}:{}".format(m.group('orig'), m.group('session'))
            sessionobj = self.sessions[key]
            nreq = int(m.group('nreq'))
            nmail = int(m.group('nmail'))
            islast = m.group('last') == self.LAST_LAST
            if sessionobj.last and nmail == 0 and nreq == sessionobj.nreq + 1:
                # new request !
                sessionobj.nreq = nreq
                sessionobj.nmail = nmail
                sessionobj.last = islast
                sessionobj.request = [msgforme]
                LOGGER.debug("Session %s: New request %s (nmail=%s last=%s)", key, nreq, nmail, islast)
            if not sessionobj.last and nreq == sessionobj.nreq and nmail == sessionobj.nmail + 1:
                # next mail in request
                sessionobj.nmail = nmail
                sessionobj.last = islast
                sessionobj.request.append(msgforme)
                LOGGER.debug("Session %s: Current request %s next email %s (last=%s)", key, nreq, nmail, islast)
            if islast:
                # handle last message
                if len(sessionobj.request) == 1 and self.TEXT_STOP in sessionobj.request[0].get_payload():
                    LOGGER.info("Session %s: Terminating", key)
                    sessionobj.socket.close()
                    del self.sessions[key]
                else:
                    # send message
                    zdata = b''.join(msg.get_payload(decode=True) for msg in sessionobj.request)
                    data = zlib.decompress(zdata)
                    LOGGER.info("Session %s: Sending data %s bytes", key, len(data))
                    sessionobj.socket.sendall(data)
            
            
    
    def openconnection(self, serverid, localport, distanthost, distantport):
        """Open a binded socket locally, and when a connection arrives, starts a session."""
        sock = socket.socket()
        sock.bind(('', int(localport)))
        sock.listen(5)
        LOGGER.info("Listening for incoming connections on port %s (for %s:%s on server %s)", localport, distanthost, distantport, serverid)
        t = threading.Thread(target=self.listentoserversocket, args=(localport, sock, serverid, distanthost, distantport))
        t.start()
    
    def listentoserversocket(self, localport, sock, serverid, distanthost, distantport):
        """Thread to listen to the server socket on the local port."""
        while True:
            # wait for a connection
            conn, adress = self.socket.accept()
            LOGGER.info("Incoming connection on port %s (from %s) (for %s:%s on server %s)", localport, adress, distanthost, distantport, serverid)
            # send e-mail message for new session
            msg = MIMEText(self.TEXT_EXPOSE_SOCKET.format(port=distantport, host=distanthost))
            msg['Subject'] = self.SUBJECT_PATTERN.format(sid=serverid, orig=self.id, session=self.SESSION_NEW,
                            nreq=0, nmail=0, last=ImapCommon.LAST_LAST)
            keyformater = serverid + ":{}"
            with self.connlock:
                # lock incoming messages before we get the new session
                self.mime2email(msg)
                # wait for session id
                response = self.waitforemail(sid=self.id, orig=serverid, session=lambda s:keyformater.format(s) not in self.sessions)
            # get and store session
            parsedsubject = self.parsesubject(response)
            session = parsedsubject.group('session')
            nreq = parsedsubject.group('nreq')
            LOGGER.info("%s is connected using session %s", adress, session)
            if nreq != '0':
                # nreq must be '0'
                LOGGER.warn("NREQ was not 0: %s", nreq)
            sessionobj = self.sessions[keyformater.format(session)] = ImapSocketClientSession(serverid, conn, adress)
            # start thread listening to socket
            t = sessionobj.listeningthread = threading.Thread(target=self.listentoclientsocket, args=(conn, serverid, session))
            t.start()
    
    def listentoclientsocket(self, conn, serverid, session):
        """Thread to listen to an incoming client socket."""
        return self.listentosocketandsendmail(conn, serverid, session)
        
        
        

# list of protocols : "protocol" => (classclient, classserver)
PROTOCOLS = {
    "IMAP": (ImapClient, ImapBashServer),
}

# ########################################### Main methods
#
#                      M   M  AAA  III N   N                                            
#                      MM MM A   A  I  NN  N                                          
#                      M M M AAAAA  I  N N N                                             
#                      M   M A   A  I  N  NN                                               
#                      M   M A   A III N   N                                                       
#                                                                                               

COMMON_ARGUMENTS = argparse.ArgumentParser(description="Remote connection server", add_help=False)
COMMON_ARGUMENTS.add_argument("--protocol", default="IMAP", help="The protocol to use (one of %s)" % ", ".join(PROTOCOLS.keys()))
COMMON_ARGUMENTS.add_argument("--host", help="Hostname to connect to", required=True)
COMMON_ARGUMENTS.add_argument("--port", help="Port of host to connect to")
COMMON_ARGUMENTS.add_argument("--user", help="The user to use")
COMMON_ARGUMENTS.add_argument("--password", help="The password to use")
COMMON_ARGUMENTS.add_argument("--credmode", default="DEFAULT", help="The credential mode (one of %s)" % ", ".join(CREDENTIAL_MANAGERS.keys()))
COMMON_ARGUMENTS.add_argument("--credfile", help="The credential file (default for the one of credmode mode)")
COMMON_ARGUMENTS.add_argument("--protectcredfile", default=False, const=True, action="store_const", help="Indicates if the credential file must be protected.")
COMMON_ARGUMENTS.add_argument("--id", default=hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:random.randrange(4,10)], help="Identifier of the instance")

def mainSocket(*args):
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser(description="Test imap connection", parents=[COMMON_ARGUMENTS], prog=args[0]+" imaptest")
    parser.add_argument("--mode", "-m", help="The mode of socket (client, server)", required=True)
    def parsetunnel(s, rx=re.compile('(?P<localport>\d+):(?P<distanthost>[a-zA-Z0-9._-]+):(?P<distantport>\d+)')):
        m = rx.match(s)
        if not m:
            raise argparse.ArgumentTypeError
        return m
    parser.add_argument("--tunnel", "-L", help="Start the tunnel directly (port-local:HOSTNAME:port-distant)", type=parsetunnel)
    parser.add_argument("--serverid", "-S", help="Default server id")
    options = parser.parse_args(args[1:])
    credmanager = CREDENTIAL_MANAGERS[options.credmode](options.credfile, not options.protectcredfile)
    
    if options.mode == "client":
        # client
        client = ImapSocketClient(options.host, credmanager, login=options.user, password=options.password, id=options.id)
        if options.tunnel:
            client.openconnection(options.serverid, int(options.tunnel.group('localport')), options.tunnel.group('distanthost'), options.tunnel.group('distantport'))
        openconnectionrx = re.compile(r"(?i)open\s+(?P<serverid>[a-zA-Z0-9._-]+)(?P<localport>\d+)\s+(?P<distanthost>[a-zA-Z0-9._-]+)\s+(?P<distantport>\d+)")
        while True:
            command = input("Command: ")
            m = openconnectionrx.match(command)
            if m:
                serverid = m.group('serverid')
                if len(serverid) == 1 and options.serverid:
                    serverid = options.serverid
                client.openconnection(serverid, int(m.group('localport')), m.group('distanthost'), m.group('distantport'))
                continue
            if command:
                # not recognized command
                print("Available commands:")
                print("    OPEN <serverid> <localport> <distanthost> <distantport>")
    else:
        # server
        server = ImapSocketServer(options.host, credmanager, login=options.user, password=options.password, id=options.id)
        LOGGER.info("ImapSocketServer %s started on %s", options.id, options.host)
    
    

def mainImaptest(*args):
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser(description="Test imap connection", parents=[COMMON_ARGUMENTS], prog=args[0]+" imaptest")
    options = parser.parse_args(args[1:])
    
    credmanager = CREDENTIAL_MANAGERS[options.credmode](options.credfile, not options.protectcredfile)
    
    server = ImapCommon()
    serverid = "testserver"
    server.connect(options.host, credmanager, login=options.user, password=options.password)
    
    client = ImapCommon()
    clientid = "testclient"
    client.connect(options.host, credmanager, login=options.user, password=options.password)
    
    teststring = "Testing string payload"
    msg = MIMEText(teststring)
    msg['Subject'] = ImapCommon.SUBJECT_PATTERN.format(sid=serverid, orig=clientid, session="-", nreq=0, nmail=0, last="last")
    
    client.mime2email(msg)
    
    returned = server.waitforemail(sid=serverid)
    
    assert returned.get_payload() == teststring, returned.get_payload()
    
    data = zlib.compress(teststring.encode()*300)
    msg = MIMEApplication(data)
    msg['Subject'] = ImapCommon.SUBJECT_PATTERN.format(sid=clientid, orig=serverid, session="-", nreq=0, nmail=0, last="last")
    
    server.mime2email(msg)
    
    returned = client.waitforemail(sid=clientid)
    
    assert returned.get_payload(decode=True) == data, returned.get_payload(decode=True)
    
    client.conn.logout()
    server.conn.logout()
    print("Test Imap ok")
    

def mainServer(*args):
    """Main for a server"""
    parser = argparse.ArgumentParser(description="Remote connection server", parents=[COMMON_ARGUMENTS], prog=args[0]+" server")
    #parser.add_argument()
    #i = ImapServer('mail.thales-services.fr')
    options = parser.parse_args(args[1:])

    protocol = PROTOCOLS.get(options.protocol)[1]
    credmanager = CREDENTIAL_MANAGERS[options.credmode](options.credfile, not options.protectcredfile)

    server = protocol(options.host, credmanager, login=options.user, password=options.password, id=options.id)

def mainClient(*args):
    """Main for a client"""
    parser = argparse.ArgumentParser(description="Remote connection client", parents=[COMMON_ARGUMENTS], prog=args[0]+" client")
    parser.parse_args(args[1:])
    options = parser.parse_args(args[1:])

    protocol = PROTOCOLS.get(options.protocol)[0]
    credmanager = CREDENTIAL_MANAGERS[options.credmode](options.credfile, not options.protectcredfile)
    client = protocol(options.host, credmanager, login=options.user, password=options.password, id=options.id)

def mainHelp(*args):
    """Main for help"""
    othermain = args[1] if args[1:] else None
    if othermain and ("main"+othermain.title()) in globals():
        return globals()["main"+othermain.title()](*[args[0], "--help"])
    mains = {k[4:].lower():globals()[k] for k in globals() if k.startswith("main")}
    print("Usage:", args[0], "[%s] [options...]" % "|".join(sorted(mains.keys())))
    if othermain is None:
        for main, mainMethod in sorted(mains.items()):
            if main == "help": continue
            try:
                print("*********", main, "mode ***********")
                mainMethod(*[args[0], "--help"])
            except:
                pass


if __name__ == "__main__":
    if not sys.argv[1:] or not ("main"+sys.argv[1].title()) in globals():
        print("Usage:", sys.argv[0], "[help|client|server] [--help|options...]")
    else:
        mmain = "main"+sys.argv[1].title()
        del sys.argv[1]
        globals()[mmain](*sys.argv)
