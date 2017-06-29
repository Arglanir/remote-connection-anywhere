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

###################################### CREDENTIALS

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
            except json.JSONDecodeError as e:
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

########################################## Command/responses

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

######################################## Clients

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

######################################### Responders

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

##################################### Servers

class ServerBase:
    def __init__(self, proxyaddr, credmanager, id):
        LOGGER.warn("Creating %s to %s with id=%s", type(self).__name__, proxyaddr, id)
        self.proxyaddr = proxyaddr
        self.credmanager = credmanager
        self.id = id

####################################### IMAP Protocol

class ImapCommon:
    EXPECTED_SUBJECT = "RemoteConnection"
    # sid: server id
    # orig: origin: client/server
    # session: # of server session (- when starting session)
    # nreq: # of request (incremental)
    # nmail: # of e-mail (incremental)
    # last: "-" if not last, "last" if last
    SUBJECT_PATTERN = EXPECTED_SUBJECT + r" sid{sid}, orig{orig}, session{session}, nreq{nreq}, nmail{nmail}, last{last},"
    SUBJECT_RX = re.compile(re.sub(r"{(\w+)\}", r"(?P<\1>[a-zA-Z0-9*_.-]+)", SUBJECT_PATTERN))
    SUBJECT_GROUPS = 'sid orig session nreq nmail last'.split()
    SEARCH_SUBJECT_PATTERN = "{group}{value},"
    parser = BytesParser()

    def connect(self, hostname, credmanager, login=None, password=None):
        self.credmanager = credmanager
        self.conn = imaplib.IMAP4(hostname)
        self.conn.starttls()
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
        self.conn.select()

    def email2mime(self, uid):
        """Read an e-mail from the IMAP server."""
        typ, resp = self.conn.uid('fetch', uid, '(RFC822)')
        message = parser.parsebytes(resp[1][0][1])
        return message

    def deleteemail(self, uid):
        """Delete an used e-mail from the server"""
        typ, resp = self.conn.uid('store', uid, r'+FLAGS \Deleted')
        self.conn.expunge()

    def mime2email(self, mime):
        """Write an e-mail to the IMAP server."""
        # FIXME: todo
        pass

    def waitforemail(self, sid=None, orig=None, session=None, nreq=None, nmail=None, last=None):
        """Wait for a specific email and return it."""
        othersearch = []
        for grp in self.SUBJECT_GROUPS:
            if type(locals()[grp]) is str:
                othersearch.append('SUBJECT')
                othersearch.append(self.SEARCH_SUBJECT_PATTERN.format(grp, locals()[grp]))
        found = None
        while not found:
            # searching e-mails
            typ, uids = self.conn.uid('search', "SUBJECT", self.EXPECTED_SUBJECT, *othersearch)
            if not uids[0]:
                time.sleep(self.SEARCH_INTERVAL)
                continue
            # fetching them all
            typ, responses = self.conn.uid('fetch', ",".join(uids[0].decode().split()), "(UID RFC822.HEADER)")
            for response in responses[1]:
                if type(header) is not tuple:
                    continue
                # read response header
                _msgnum, _, uid, _, hsize = response[0].decode().split()
                # hsize = int(hsize.replace('{','').replace('}'))
                sheader = response[1]
                header = parser.parsebytes(sheader)
                subject = header['Subject']
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
                            break
                # stop if ok
                if corresponds:
                    found = uid
                    break
                if found: break
            if found: break
            time.sleep(self.SEARCH_INTERVAL)
        # fetch full e-mail
        return self.email2mime(found)


testm = ImapCommon.SUBJECT_RX.match(ImapCommon.SUBJECT_PATTERN.replace("{","").replace("}","---"))
assert testm
assert all(k+"---" == testm.group(k) for k in "sid orig session nreq nmail last".split())

class ImapServer(ServerBase, ImapCommon):
    SEARCH_INTERVAL = 2 # in seconds

    def __init__(self, hostname, credmanager, login=None, password=None, id=None):
        super().__init__(hostname, credmanager, id)
        self.connect(hostname, credmanager, login, password)
        self.t = threading.Thread(target=self.loop)
        self.t.start()

    def loop(self):
        while True:
            self.search()
            time.sleep(self.SEARCH_INTERVAL)

    def search(self):
        typ, msgnums = self.conn.search(None, "SUBJECT", self.EXPECTED_SUBJECT)
        print("Search response:", typ, msgnums)
        for msgnum in msgnums[0].split():
            resp = self.conn.fetch(msgnum, "(RFC822.HEADER)")
            sheader = resp[1][0][1]
            header = parser.parsebytes(sheader)
            subject = header['Subject']



class ImapBashServer(ImapServer):
    """Server that executes bash commands."""
    def __init__(self, hostname, credmanager, login=None, password=None, id=None):
        ImapServer.__init__(self, hostname, credmanager, login, password, id)


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

class ImapSocketServer(ImapServer):
    """Server that forwards a port."""
    def __init__(self, hostname, credmanager, login=None, password=None, id=None):
        ImapServer.__init__(self, hostname, credmanager, login, password, id)


class ImapSocketClient(ClientBase, ImapCommon):
    def __init__(self, hostname, credmanager, login=None, password=None, id=None):
        super().__init__(hostname, credmanager, id)
        self.connect(hostname, credmanager, login, password)

# list of protocols : "protocol" => (classclient, classserver)
PROTOCOLS = {
    "IMAP": (ImapClient, ImapBashServer),
}

############################################ Main methods

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
