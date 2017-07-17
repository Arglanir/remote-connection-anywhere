# Remote-connection-anywhere

## Short description
I created this project in order to create connections to an otherwise protected zone, through async means (shared folder, e-mail)

It shows also some tests when working with sockets.

## How to run it

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
