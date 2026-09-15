from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import product_handoff, interface_node
from app.artifact_factory import ArtifactFactory


class ProductHandoffTests(unittest.TestCase):
    def setUp(self):
        base=Path(os.environ['PRIME_DATA_DIR']).parent/('product-handoff-'+uuid.uuid4().hex)
        self.data=base/'runtime/data';self.data.mkdir(parents=True)
        self.root=base/'outputs/transfer';self.root.mkdir(parents=True)
        self.config=self.data.parent/'product-handoff.json'
        self.policy={'directory':str(self.root),'issued_at':time.time()-1,'expires_at':time.time()+300}
        self.write_config()
        (self.root/'JARVIS-DELL-PRODUCTION-RECONNECT.zip').write_bytes(b'public fixture bundle only')
        clients={name:{'token_sha256':hashlib.sha256(name.encode()).hexdigest(),'expires_at':time.time()+300,
                      'capabilities':['task.read']} for name in ('dell:DESKTOP-IPV4PH9','other')}
        self.env=patch.dict(os.environ,{'PRIME_DATA_DIR':str(self.data),'PRIME_INTERFACE_CLIENTS_JSON':json.dumps(clients)})
        self.env.start()
        app=FastAPI();app.include_router(product_handoff.router)
        self.app=app
        self.client=TestClient(app,base_url='https://abex.test',client=('192.168.1.17',12345))
        db=interface_node.db_connect()
        db.execute('INSERT INTO requests VALUES(?,?,?,?)',('dell:DESKTOP-IPV4PH9','one','fixture','task-fixture'))
        db.commit();db.close()
        self.artifact=ArtifactFactory(self.data/'artifacts').create(kind='json',content='{"fixture":true}',
            task_id='task-fixture',creator='fixture',provenance='isolated handoff verification')
        self.value={'host':'DESKTOP-IPV4PH9','client_id':'dell:DESKTOP-IPV4PH9','task_id':'task-fixture',
            'artifact_id':self.artifact['artifact_id'],'sha256':self.artifact['sha256'],
            'download_sha256':self.artifact['sha256'],'readback_sha256':self.artifact['sha256'],
            'identity_pass':True,'tls_pass':True,'health_pass':True,'reconnect_pass':True,'idempotency_pass':True,'status':'PASS'}

    def tearDown(self):self.client.close();self.env.stop()
    def write_config(self):self.config.write_text(json.dumps(self.policy))
    def headers(self,name='dell:DESKTOP-IPV4PH9'):
        return {'X-Client-ID':name,'Authorization':'Bearer '+name}
    def submit(self,value=None,raw=None,headers=None):
        content=raw if raw is not None else json.dumps(value or self.value,sort_keys=True).encode()
        return self.client.post('/integration/production-proof',content=content,headers={
            **self.headers(),'X-Content-SHA256':hashlib.sha256(content).hexdigest(),**(headers or {})})

    def test_disabled_expired_future_and_peer_transport_bounds(self):
        self.config.unlink()
        assert self.client.get('/integration/production-client.zip').status_code==404
        for issued,expiry in [(time.time()-20,time.time()-1),(time.time()+10,time.time()+20),(time.time()-1,time.time()+90000)]:
            self.policy.update(issued_at=issued,expires_at=expiry);self.write_config()
            assert self.client.get('/integration/production-client.zip').status_code==404
        self.policy.update(issued_at=time.time()-1,expires_at=time.time()+300);self.write_config()
        for scheme,host in [('https','192.168.1.18'),('http','192.168.1.17')]:
            with TestClient(self.app,base_url=scheme+'://abex.test',client=(host,12345)) as other:
                assert other.get('/integration/production-client.zip',headers={'X-Forwarded-For':'192.168.1.17'}).status_code==404
        with patch.dict(os.environ):
            os.environ.pop('PRIME_DATA_DIR')
            assert self.client.get('/integration/production-client.zip').status_code==404
        self.policy['directory']=str(self.data)
        self.write_config()
        assert self.client.get('/integration/production-client.zip').status_code==404

    def test_proof_auth_ownership_hash_and_schema_bounds(self):
        assert self.submit(headers={'Authorization':'Bearer wrong'}).status_code==401
        assert self.submit(headers=self.headers('other')).status_code==403
        assert self.submit({**self.value,'task_id':'another-task'}).status_code==404
        assert self.submit(headers={'X-Content-SHA256':'0'*64}).status_code==422
        assert self.submit({**self.value,'readback_sha256':'0'*64}).status_code==422
        assert self.submit({**self.value,'identity_pass':1}).status_code==422
        assert self.submit({**self.value,'extra':'not-in-schema'}).status_code==422
        assert self.submit(raw=b'x'*8193).status_code==413
        duplicated=json.dumps(self.value)[:-1]+',"status":"PASS"}'
        assert self.submit(raw=duplicated.encode()).status_code==422
        foreign=ArtifactFactory(self.data/'artifacts').create(kind='json',content='{"fixture":true}',
            task_id='foreign-task',creator='fixture',provenance='ownership fixture')
        assert self.submit({**self.value,'artifact_id':foreign['artifact_id']}).status_code==422
        assert not (self.root/'TRANSFER_CLOSED').exists()

    def test_valid_durable_receipt_closure_and_idempotent_repeat(self):
        assert self.client.get('/integration/production-client.zip').status_code==200
        with patch.object(product_handoff.os,'fsync',wraps=os.fsync) as fsync:
            response=self.submit()
        assert response.status_code==200,response.text
        assert fsync.call_count==2
        digest=response.json()['sha256'];target=self.root/('DELL-PROOF-'+digest+'.json')
        raw=target.read_bytes();stamp=target.stat().st_mtime_ns
        assert hashlib.sha256(raw).hexdigest()==digest
        assert (self.root/'TRANSFER_CLOSED').is_file()
        assert self.client.get('/integration/production-client.zip').status_code==404
        assert self.submit().json()==response.json()
        assert target.read_bytes()==raw and target.stat().st_mtime_ns==stamp

    def test_interrupted_closure_recovery_and_receipt_tamper(self):
        raw=json.dumps(self.value,sort_keys=True).encode();digest=hashlib.sha256(raw).hexdigest()
        target=self.root/('DELL-PROOF-'+digest+'.json');target.write_bytes(raw)
        assert self.submit().status_code==200
        assert (self.root/'TRANSFER_CLOSED').exists()
        target.write_bytes(b'corrupt fixture')
        assert self.submit().status_code==409
        assert target.read_bytes()==b'corrupt fixture'

    def test_concurrent_identical_proofs_and_new_proof_after_closure(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.submit(),range(2)))
        assert [result.status_code for result in results]==[200,200]
        assert results[0].json()==results[1].json()
        # Same semantic proof serialized differently is distinct evidence; closed transfer rejects it.
        assert self.submit(raw=json.dumps(self.value,indent=2).encode()).status_code==409

    def test_versioned_download_separate_bytes_and_original_proof_receipt(self):
        root2=self.root.parent/'transfer-v2';root2.mkdir()
        (root2/'JARVIS-DELL-PRODUCTION-RECONNECT.zip').write_bytes(b'corrected fixture v2')
        config2=self.config.with_name('product-handoff-v2.json')
        config2.write_text(json.dumps({**self.policy,'directory':str(root2)}))
        before=self.config.read_bytes()
        assert self.client.get('/integration/production-client.zip').content==b'public fixture bundle only'
        assert self.client.get('/integration/production-client-v2.zip').content==b'corrected fixture v2'
        response=self.submit();assert response.status_code==200
        assert (self.root/('DELL-PROOF-'+response.json()['sha256']+'.json')).is_file()
        assert not list(root2.glob('DELL-PROOF-*'))
        assert self.client.get('/integration/production-client-v2.zip').status_code==404
        assert self.config.read_bytes()==before

    def test_versioned_download_fail_closed_bounds(self):
        route='/integration/production-client-v2.zip'
        assert self.client.get(route).status_code==404
        config2=self.config.with_name('product-handoff-v2.json')
        for change in ({'expires_at':time.time()-1},{'issued_at':time.time()+10},
                       {'expires_at':time.time()+90000},{'directory':str(self.data)}):
            config2.write_text(json.dumps({**self.policy,**change}))
            assert self.client.get(route).status_code==404
        config2.write_text(json.dumps(self.policy))
        for scheme,host in [('https','192.168.1.18'),('http','192.168.1.17')]:
            with TestClient(self.app,base_url=scheme+'://abex.test',client=(host,12345)) as other:
                assert other.get(route,headers={'X-Forwarded-For':'192.168.1.17'}).status_code==404
        assert self.client.get(route).status_code==200
        self.config.unlink()
        assert self.client.get(route).status_code==404


if __name__=='__main__':unittest.main()
