# Remote-connection-anywhere

## Short description
I created this project in order to create connections to an otherwise protected zone, through async means (shared folder, e-mail)

It shows also some tests when working with sockets.

## Architecture

Communication client ⇆ Communication layer ⇆ Action server

### Communication layers

Client ⇆ Session ⇆ Physical mean ⇆ Session ⇆ Server

* ✅ Bases classes (`[CommunicationSession CommunicationClient CommunicationServer](src/remoteconanywhere/communication.py))`)
* ✅ Test communication through queue (`[QueueCommunicationSession](src/remoteconanywhere/communication.py))`)
* ✅  Exchange of files through folder (like NFS, or shared folder) (`[FolderCommunicationSession FolderCommClient FolderCommServer](src/remoteconanywhere/communication.py))`)
* 💡 FTP
* 💡  Imap (e-mail server)
* 💡 Socket (not really useful)

### Action clients / servers

* ✅ For test: (`[QueueCommunicationSession](test/remoteconanywhere/test_communication_folder.py))`
* ✅ Console / ✅Shell (Bash or other program) communicating with stdin/stdout/stderr  (`[GenericPipeActionServer PipeActionServer PipeLineClient](src/remoteconanywhere/pipe.py))`
* 💡 Socket / Connection to other socket (ssh, rdesktop, vnc)
* 💡 Socket / Connection to local socket
* 💡 Http proxy
* 💡 SOCKS proxy ?

💡 : ideas 

🚧 : in construction

✅ : complete

### Credential managers
See [src/remoteconanywhere/cred.py](src/remoteconanywhere/cred.py)
* ✅  .netrc file
* ✅ local file  

## How to run it
```python
###### on the server side:

from remoteconanywhere.communication import *
from remoteconanywhere.pipe import *

# choose and configure one server
server = FolderCommServer('/path/to/folder')
# register action servers
server.registerCapability(GenericPipeActionServer())
server.registerCapability(PipeActionServer(sys.executable, '-i', '-u'))
server.registerCapability(PipeActionServer('/bin/bash', '-i'))
# start the server
server.serveForever()



###### on the client side:
# select the client to use
client = FolderCommClient('/path/to/folder')
# check server/capabilities
client.listServers()
client.capabilities('serverid')
# open a session, give it to the capability client
session = client.openSession('serverid', 'pipe')
PipeLineClient(session).start()

```



## How to run it (old)
🚧 In construction, old API

```bash
python3 test_socket.py asyncio 8910 www.google.com 443 &
wget --no-check-certificate https://127.0.0.1:8910
```


```bash
python3 remoteconanywhere.py --help
```

```bash
python3 remoteconanywhere.py imaptest --host imap.gmail.com:ssl
```
