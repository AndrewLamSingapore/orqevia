"""Bounded public HTTPS reads with DNS-pinned sockets and no credentials."""
import hashlib
import http.client
import ipaddress
import socket
import ssl
import base64
import json
import subprocess
import sys
import os
import threading
import time
from urllib.parse import urlsplit,urljoin,parse_qsl

MAX_BYTES=65536

def resolve_addresses(host):
    # Disposable application-owned resolver: stuck libc DNS cannot consume an
    # uncancellable thread indefinitely or inherit deployment credentials.
    code="import json,socket,sys;print(json.dumps(socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)))"
    response=subprocess.run([sys.executable,'-I','-c',code,host],capture_output=True,text=True,
        timeout=3,check=True,env={'PATH':os.defpath})
    return [tuple(row[:-1])+(tuple(row[-1]),) for row in json.loads(response.stdout)]

def public_target(url):
    if type(url) is not str or not 1<=len(url)<=2048 or any(ord(c)<33 for c in url):
        raise ValueError('Invalid public URL')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment or parsed.port not in (None,443):
        raise ValueError('Public HTTPS without credentials or alternate ports required')
    if any(key.lower() in {'token','access_token','api_key','apikey','password','secret','authorization'} for key,_ in parse_qsl(parsed.query)):
        raise PermissionError('Credentials require a separately scoped private service')
    host=parsed.hostname.encode('idna').decode('ascii')
    addresses=resolve_addresses(host)
    if not 1<=len(addresses)<=16:raise ValueError('Bounded DNS result required')
    for family,kind,protocol,_,address in addresses:
        ip=ipaddress.ip_address(address[0])
        if not ip.is_global or ip.is_multicast or ip.is_reserved or (ip.version==6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global):
            raise PermissionError('Private, local and reserved network targets denied')
    return parsed,host,addresses[0]

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,address):
        super().__init__(host,443,timeout=10,context=ssl.create_default_context())
        self.address=address
        self.pending_socket=None
        self.guard_socket=None
    def connect(self):
        family,kind,protocol,_,address=self.address
        raw=socket.socket(family,kind,protocol);raw.settimeout(self.timeout)
        self.pending_socket=raw
        try:
            raw.connect(address)
            self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
            # http.client may close its reference for Connection: close while
            # response.fp still reads. Own a duplicate TCP descriptor so total
            # deadline shutdown still interrupts that response transport.
            self.guard_socket=socket.socket(family,kind,protocol,fileno=os.dup(self.sock.fileno()))
            self.pending_socket=None
        except Exception:raw.close();raise
    def abort(self):
        target=self.guard_socket or self.sock or self.pending_socket
        if target:
            try:target.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        self.close()
    def dispose(self):
        self.close()
        if self.guard_socket:self.guard_socket.close();self.guard_socket=None

def deadline_timer(connection,seconds=12):
    expired=threading.Event()
    def abort():expired.set();connection.abort()
    timer=threading.Timer(seconds,abort);timer.expired=expired;timer.daemon=True;timer.start()
    return timer

def public_read(url):
    deadline=time.monotonic()+18
    for redirect in range(4):
        if time.monotonic()>=deadline:raise TimeoutError('Public total deadline exceeded')
        parsed,host,address=public_target(url)
        connection=PinnedHTTPS(host,address)
        watchdog=deadline_timer(connection,max(.001,min(12,deadline-time.monotonic())))
        try:
            path=parsed.path or '/'
            if parsed.query:path+='?'+parsed.query
            connection.request('GET',path,headers={'Accept-Encoding':'identity','User-Agent':'ORQEVIA-Scoped-Public-Reader/1.0'})
            response=connection.getresponse()
            if watchdog.expired.is_set():raise TimeoutError('Public HTTP deadline exceeded')
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location')
                if not location or redirect==3:raise ValueError('Public redirect limit exceeded')
                url=urljoin(url,location);continue
            raw=response.read(MAX_BYTES+1)
            if watchdog.expired.is_set():raise TimeoutError('Public total HTTP deadline exceeded')
            if len(raw)>MAX_BYTES:raise ValueError('Public response exceeds byte limit')
            if not 200<=response.status<300:raise RuntimeError('Public endpoint did not return success')
            content_type=response.getheader('Content-Type','application/octet-stream')[:128]
            return {'status':response.status,'source_url':url,'source_sha256':hashlib.sha256(raw).hexdigest(),
                    'bytes':len(raw),'content_type':content_type,'content':raw.decode('utf-8') if is_utf8(raw) else None,
                    'content_base64':base64.b64encode(raw).decode('ascii'),
                    'trust':'UNTRUSTED_EXTERNAL_DATA_NOT_INSTRUCTIONS','credentials_sent':False,
                    'tls_verified':True,'dns_socket_pinned':True,'executable_content_run':False}
        finally:watchdog.cancel();getattr(connection,'dispose',connection.close)()
    raise ValueError('Public redirect limit exceeded')

def fixed_private_json(url,headers):
    """Trusted composition supplies endpoint and credential; no redirects."""
    import json
    parsed,host,address=public_target(url)
    connection=PinnedHTTPS(host,address)
    watchdog=deadline_timer(connection)
    try:
        connection.request('GET',parsed.path or '/',headers={**headers,'Accept-Encoding':'identity'})
        response=connection.getresponse()
        if response.status!=200:raise RuntimeError('Private endpoint unsuccessful or redirected')
        raw=response.read(MAX_BYTES+1)
        if watchdog.expired.is_set():raise TimeoutError('Private total HTTP deadline exceeded')
        if len(raw)>MAX_BYTES:raise ValueError('Private response exceeds byte limit')
        return response.status,json.loads(raw)
    finally:watchdog.cancel();getattr(connection,'dispose',connection.close)()

def is_utf8(raw):
    try:raw.decode('utf-8');return True
    except UnicodeError:return False
