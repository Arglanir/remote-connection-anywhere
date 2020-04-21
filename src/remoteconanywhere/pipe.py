'''
Action server that starts a program, sends input to this program, and sends the output and error to the client.

Created on 7 avr. 2020

@author: Cedric
'''
import os
import threading
import logging
import subprocess
import queue
import time
import shlex
import sys
from remoteconanywhere.communication import ActionServer, QueueCommunicationSession

LOGGER = logging.getLogger(os.path.basename(__file__).replace(".py", ""))




class GenericPipeActionServer(ActionServer):
    STDOUT_HEADER = b'STDOUT'
    STDERR_HEADER = b'STDERR'
    INFO_HEADER = b'INFO'
    ERROR_HEADER = b'PROBLEM'
    

    def __init__(self, name='pipe'):
        super().__init__(name)
    
    def start(self, session):
        ActionServer.start(self, session)
        threading.Thread(target=self.mainLoop, name="%s-%s" % (self.capability, session.sid), args=(session,)).start()
    
    def createProcess(self, session):
        '''Creates the process that will be given by the session.
        In the first message, the first line is split, this is the program to run'''
        while not session.checkIfDataAvailable():
            time.sleep(0.01)
        data = session.receiveChunk().decode()
        lines = [l.trim() for l in data.split('\n')]
        # first line for the program
        programAndArgs = shlex.split(lines[0])
        # TODO: add cwd and environment
        LOGGER.debug("Starting %s", programAndArgs)
        try:
            process = subprocess.Popen(programAndArgs, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **self.kwargs)
        except Exception as e:
            LOGGER.warning("Impossible to start %s: %s", programAndArgs, e)
            session.send(self.ERROR_HEADER + str(e).encode('utf-8', errors='replace'))
            raise
        return process
    
    def mainLoop(self, session):
        process = self.createProcess(session)
        finishedReading = [False, False]
        threading.Thread(target=self.pipeReaderThread, name="%s-%s-reader" % (self.capability, session.sid),
                         args=(session, process, finishedReading)).start()
        LOGGER.info("%s started, session %s", self.program, session.sid)
        while not session.closed and process.poll() is None:
            received = session.receiveChunk()
            if received:
                LOGGER.info("%s session %s received a chunk of %s bytes", self.basename, session.sid, len(received))
                process.stdin.write(received)
                process.stdin.flush()
            if received is None:
                LOGGER.debug("Ending session %s as client disconnected.", session.sid)
                break
            time.sleep(0.01)
        if process.poll() is not None:
            # program was terminated naturally
            session.send(self.INFO_HEADER+str(process.returncode).encode())
            # wait to read everything
            while not all(finishedReading):
                time.sleep(0.01)
            session.close()
        LOGGER.debug("%s session %s stopping... Process state: %s", self.basename, session.sid, process.poll())
        process.kill()
        LOGGER.info("%s session %s stopped", self.basename, session.sid)
        
    def monoPipeReaderThreadByByte(self, session, stream, header, funcend):
        '''Reads the pipe and sends the data to the session, with the given header'''
        mqueue = queue.Queue()
        threading.Thread(target=self.monoPipeReaderThreadByByteHelper, name="%s-sender" % (threading.currentThread().name),
                         args=(session, header, mqueue, funcend)).start()
        byte = b'nothingyet'
        bytesread = 0
        while byte:
            # will return b'' if stream is closed
            byte = stream.read(1)
            bytesread += len(byte) if byte else 0
            mqueue.put(byte)
        LOGGER.debug("End of reading of stream %s: %s bytes read", header.decode(), bytesread)
    
    def monoPipeReaderThreadByByteHelper(self, session, header, mqueue, funcend):
        '''Reads the pipe and sends the data to the session, with the given header'''
        LOGGER.debug("Start of reading of stream %s", header.decode())
        received = bytearray()
        bytesread = 0
        while True:
            try:
                byte = mqueue.get(timeout=0.01)
            except queue.Empty:
                if received:
                    session.send(header + received)
                    received = bytearray()
                continue
            if not byte:
                # end of stream
                break
            if isinstance(byte, bytes):
                bytesread += len(byte) if byte else 0
                if len(received) + len(header) + len(byte) > session.maxdatalength:
                    # send now, do not split message as we need the header on the client side
                    session.send(header + received)
                    received = bytearray()
                # some more data
                received.extend(byte)
            else:
                LOGGER.warn("Received something that is not a byte: %r", byte)
        # sending remaining data
        if received:
            session.send(header + received)
        LOGGER.debug("End of reading2 of stream %s, %s bytes received and sent", header.decode(), bytesread)
        funcend()
        
    def pipeReaderThreadDispatch(self, session, process, finishedReading):
        '''Reads the pipe and sends the data to the session, with the given header'''
        def funcFinishReading(index):
            def torun():
                finishedReading[index] = True
            return torun
        threading.Thread(target=self.monoPipeReaderThreadByByte, args=(session, process.stdout, self.STDOUT_HEADER,
                                                                       funcFinishReading(0)),
                         name='%s-%s-stdout' % (threading.currentThread().name, session.sid)).start()
        threading.Thread(target=self.monoPipeReaderThreadByByte, args=(session, process.stderr, self.STDERR_HEADER,
                                                                       funcFinishReading(1)),
                         name='%s-%s-stderr' % (threading.currentThread().name, session.sid)).start()
    
    # select depending on system
    pipeReaderThread = pipeReaderThreadDispatch # if os.name == 'nt' else pipeReaderThreadWithSelect


class PipeActionServer(GenericPipeActionServer):
    def __init__(self, program, *args, **kwargs):
        self.program = program
        self.args = args
        self.kwargs = kwargs
        self.basename = basename = os.path.basename(program).replace('.exe', '')
        super().__init__("pipe-" + basename)
    
    def createProcess(self, session):
        process = subprocess.Popen([self.program] + list(self.args), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **self.kwargs)
        return process


class PipeLineClient():
    '''Uses a client session to communicate through the pipe''' 
    def __init__(self, session):
        '''Constructor'''
        self.session = session
    
    def loopForIncomingStreams(self):
        '''Read what comes from the session and displays it using print.'''
        LOGGER.info("Starting pipe line client")
        while not self.session.closed:
            data = self.session.receiveChunk()
            if data is None:
                break
            if data:
                if data.startswith(GenericPipeActionServer.STDOUT_HEADER):
                    print(data[len(GenericPipeActionServer.STDOUT_HEADER):].decode(errors='replace'), end='')
                elif data.startswith(GenericPipeActionServer.STDERR_HEADER):
                    print(data[len(GenericPipeActionServer.STDERR_HEADER):].decode(errors='replace'), file=sys.stderr, end='')
                elif data.startswith(GenericPipeActionServer.INFO_HEADER):
                    LOGGER.info("Received info: %s", data[len(GenericPipeActionServer.INFO_HEADER):].decode(errors='replace'))
                else:
                    LOGGER.warning('Received message from session: %r', data)
        LOGGER.info("Ending pipe line client, session closed: %s", self.session.closed)
    
    def getInput(self):
        '''Function that can be mocked during tests'''
        return input()
    
    def start(self):
        '''Start listening to input, and starts the thread to listen from the session'''
        threading.Thread(target=self.loopForIncomingStreams, name='receive-data-from-%s' % self.session.other).start()
        while not self.session.closed:
            try:
                data = self.getInput()
                data += "\n"
                tosend = data.encode('utf-8')
                if not self.session.closed:
                    self.session.send(tosend)
            except (KeyboardInterrupt, EOFError):
                self.session.close()
                time.sleep(0.1)
        LOGGER.info('End of communication')
            
def main(args=(sys.executable, '-i', '-u')):
    '''Runs a pipe server and a pipe client'''
    logging.basicConfig(level='DEBUG', format='%(asctime)-15s %(levelname)-5s %(module)s.%(funcName)s [%(threadName)s] %(message)s')
    # create server
    actionserver = PipeActionServer(*args)
    # create sessions
    sessionS = QueueCommunicationSession('server')
    sessionC = QueueCommunicationSession('client')
    sessionS.inexorablyLinkQueue(sessionC)
    # start client and server
    client = PipeLineClient(sessionC)
    actionserver.start(sessionS)
    client.start()

if __name__ == '__main__':
    main()
