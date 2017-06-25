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
from email.parser import BytesParser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

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

class ClientBase:
    """Base class for a client"""
    def __init__(self, proxyaddr):
        self.proxyaddr = proxyaddr

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

TIME_BETWEEN_CALLS = 1

class BashResponder(Responder):
    """Executor of bash commands"""
    END_OF_PROGRAM = "@@@END_OF_PROGRAM_{}@@@CODE:$__code"
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
            time.sleep(TIME_BETWEEN_CALLS)
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
        time.sleep(TIME_BETWEEN_CALLS)
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

class ServerBase:
    pass


class ImapCommon:
    EXPECTED_SUBJECT = "RemoteConnection"
    SUBJECT_PATTERN = EXPECTED_SUBJECT + r" {sid} {orig} {session} {nreq} {nmail} {last}"
    SUBJECT_RX = re.compile(re.sub(r"{(\w+)\}", r"(?P<\1>[a-z0-9-]+)", SUBJECT_PATTERN))

class ImapServer(ServerBase, ImapCommon):
    SEARCH_INTERVAL = 2 # in seconds
    
    parser = BytesParser()
    def __init__(self, hostname):
        self.conn = imaplib.IMAP4(hostname)
        self.conn.starttls()
        login, account, password = netrc.netrc().authenticators(hostname)
        self.conn.login(login, password)
        self.conn.select()
        self.t = threading.Thread(target=self.loop)
        self.t.start()
    def loop(self):
        while True:
            self.search()
            time.sleep(self.SEARCH_INTERVAL)

    def search(self):
        typ, msgnums = self.conn.search(None, "SUBJECT", self.EXPECTED_SUBJECT)
        print(typ, msgnum)
        for msgnum in msgnums[0].split():
            resp = self.conn.fetch(msgnum, "(RFC822.HEADER)")
            sheader = resp[1][0][1]
            header = parser.parsebytes(sheader)
            subject = header['Subject']



class ImapBashServer(BashResponder, ImapServer):
    pass


class ImapClient(ClientBase, ImapCommon):
    SEARCH_INTERVAL = 5
    def __init__(self, hostname):
        super().__init__(hostname)
        self.conn = imaplib.IMAP4(hostname)
        self.conn.starttls()
        login, account, password = netrc.netrc().authenticators(hostname)
        self.conn.login(login, password)
        self.conn.select()
        self.t = threading.Thread(target=self.loop)
        self.t.start()
    def loop(self):
        while True:
            #self.conn.noop()
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





def main():
    i = ImapServer('mail.thales-services.fr')

if __name__ == "__main__":    
    main()
