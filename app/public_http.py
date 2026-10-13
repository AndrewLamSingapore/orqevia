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
from datetime import datetime,timezone

MAX_BYTES=65536
TOTAL_SECONDS=18

def remaining_time(deadline):
    remaining=deadline-time.monotonic()
    if remaining<=0:raise TimeoutError('HTTP total deadline exceeded')
    return remaining

def resolve_addresses(host,timeout=3):
    # Disposable application-owned resolver: stuck libc DNS cannot consume an
    # uncancellable thread indefinitely or inherit deployment credentials.
    code="import json,socket,sys;print(json.dumps(socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)))"
    response=subprocess.run([sys.executable,'-I','-c',code,host],capture_output=True,text=True,
        timeout=timeout,check=True,env={'PATH':os.defpath})
    return [tuple(row[:-1])+(tuple(row[-1]),) for row in json.loads(response.stdout)]

def public_target(url,deadline=None):
    if type(url) is not str or not 1<=len(url)<=2048 or '\\' in url or any(ord(c)<33 or ord(c)==127 for c in url):
        raise ValueError('Invalid public URL')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment or parsed.port not in (None,443):
        raise ValueError('Public HTTPS without credentials or alternate ports required')
    if any(key.lower() in {'token','access_token','api_key','apikey','password','secret','authorization'} for key,_ in parse_qsl(parsed.query)):
        raise PermissionError('Credentials require a separately scoped private service')
    host=parsed.hostname.encode('idna').decode('ascii')
    addresses=resolve_addresses(host,timeout=min(3,remaining_time(deadline))) if deadline is not None else resolve_addresses(host)
    if deadline is not None:remaining_time(deadline)
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
        self.abort_lock=threading.Lock()
        self.aborted=False
    def connect(self):
        family,kind,protocol,_,address=self.address
        raw=socket.socket(family,kind,protocol);raw.settimeout(self.timeout)
        with self.abort_lock:
            if self.aborted:raw.close();raise TimeoutError('HTTP connection deadline exceeded')
            self.pending_socket=raw
        try:
            raw.connect(address)
            # http.client may close its reference for Connection: close while
            # response.fp still reads. Own a duplicate TCP descriptor so total
            # deadline shutdown still interrupts TLS handshake and body reads.
            # socket.dup also supports Windows socket handles (os.dup does not).
            with self.abort_lock:
                if self.aborted:raise TimeoutError('HTTP connection deadline exceeded')
                self.guard_socket=raw.dup()
                self.sock=self._context.wrap_socket(raw,server_hostname=self.host,do_handshake_on_connect=False)
                self.pending_socket=None
            self.sock.do_handshake()
        except Exception:raw.close();self.dispose();raise
    def abort(self):
        with self.abort_lock:
            self.aborted=True
            target=self.guard_socket or self.sock or self.pending_socket
            if target:
                try:target.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            self.close()
            if self.pending_socket:self.pending_socket.close();self.pending_socket=None
    def dispose(self):
        self.close()
        if self.guard_socket:self.guard_socket.close();self.guard_socket=None

def deadline_timer(connection,seconds=12):
    expired=threading.Event()
    def abort():expired.set();connection.abort()
    timer=threading.Timer(seconds,abort);timer.expired=expired;timer.daemon=True;timer.start()
    return timer

def finish_transport(connection,watchdog,response):
    watchdog.cancel()
    watchdog.join()
    if response is not None:response.close()
    getattr(connection,'dispose',connection.close)()

def public_read(url):
    deadline=time.monotonic()+TOTAL_SECONDS
    redirects=[]
    for redirect in range(4):
        parsed,host,address=public_target(url,deadline)
        connection=PinnedHTTPS(host,address)
        connection.timeout=min(10,remaining_time(deadline))
        watchdog=deadline_timer(connection,remaining_time(deadline))
        response=None
        try:
            path=parsed.path or '/'
            if parsed.query:path+='?'+parsed.query
            connection.request('GET',path,headers={'Accept-Encoding':'identity','User-Agent':'ORQEVIA-Scoped-Public-Reader/1.0'})
            response=connection.getresponse()
            if watchdog.expired.is_set():raise TimeoutError('Public HTTP deadline exceeded')
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location')
                if not location or redirect==3:raise ValueError('Public redirect limit exceeded')
                redirects.append({'source_url':url,'status':response.status})
                url=urljoin(url,location);continue
            raw=response.read(MAX_BYTES+1)
            if watchdog.expired.is_set():raise TimeoutError('Public total HTTP deadline exceeded')
            remaining_time(deadline)
            if len(raw)>MAX_BYTES:raise ValueError('Public response exceeds byte limit')
            if not 200<=response.status<300:raise RuntimeError('Public endpoint did not return success')
            content_type=response.getheader('Content-Type','application/octet-stream')[:128]
            return {'status':response.status,'source_url':url,'source_sha256':hashlib.sha256(raw).hexdigest(),
                    'bytes':len(raw),'content_type':content_type,'content':raw.decode('utf-8') if is_utf8(raw) else None,
                    'content_base64':base64.b64encode(raw).decode('ascii'),
                    'observed_at':datetime.now(timezone.utc).isoformat(),'redirects':redirects,
                    'destination_ip':address[4][0],
                    'trust':'UNTRUSTED_EXTERNAL_DATA_NOT_INSTRUCTIONS','credentials_sent':False,
                    'tls_verified':True,'dns_socket_pinned':True,'executable_content_run':False}
        finally:finish_transport(connection,watchdog,response)
    raise ValueError('Public redirect limit exceeded')

def fixed_private_json(url,headers):
    """Trusted composition supplies endpoint and credential; no redirects."""
    import json
    deadline=time.monotonic()+TOTAL_SECONDS
    parsed,host,address=public_target(url,deadline)
    connection=PinnedHTTPS(host,address)
    connection.timeout=min(10,remaining_time(deadline))
    watchdog=deadline_timer(connection,remaining_time(deadline))
    response=None
    try:
        connection.request('GET',parsed.path or '/',headers={**headers,'Accept-Encoding':'identity'})
        response=connection.getresponse()
        if response.status!=200:raise RuntimeError('Private endpoint unsuccessful or redirected')
        raw=response.read(MAX_BYTES+1)
        if watchdog.expired.is_set():raise TimeoutError('Private total HTTP deadline exceeded')
        remaining_time(deadline)
        if len(raw)>MAX_BYTES:raise ValueError('Private response exceeds byte limit')
        data=json.loads(raw)
        if not isinstance(data,dict):raise ValueError('Private endpoint object required')
        return response.status,data
    finally:finish_transport(connection,watchdog,response)

def is_utf8(raw):
    try:raw.decode('utf-8');return True
    except UnicodeError:return False
