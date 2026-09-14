"""Portable deterministic client release: Python 3.10+ and existing Node 20+."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import uuid
import zipfile

SOURCE=Path(__file__).resolve().parents[1]
PIN='3358598e7fa267a9412f4c6a50482e6dd12db305d2405d1a1eafa21251be4caf'
def sha(data):return hashlib.sha256(data).hexdigest()

def package(source,archive,evidence,node='node',build=False):
    source=Path(source).resolve();archive=Path(archive).resolve()
    if sha((source/'lib/upstream.mjs').read_bytes())!=PIN:raise ValueError('UNAPPROVED_TRANSPORT')
    lock=json.loads((source/'SOURCE-SHA256.json').read_text())
    for name,digest in lock.items():
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:raise ValueError('UNSAFE_PATH')
        if sha((source/name).read_bytes())!=digest:raise ValueError('SOURCE_HASH_MISMATCH')
    if not {'test/url-transport.test.mjs','test/client.test.mjs','lib/upstream.mjs'}<=lock.keys():raise ValueError('INCOMPLETE_LOCK')
    content={name:(source/name).read_bytes() for name in lock}
    content['SOURCE-SHA256.json']=(source/'SOURCE-SHA256.json').read_bytes()
    if build:
        # Stored ZIP avoids compressor-version variability. Fixed timestamp,
        # permissions, order and platform remove filesystem metadata variability.
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_STORED) as z:
            for name,data in sorted(content.items()):
                info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.create_system=3
                info.external_attr=0o100644<<16;info.compress_type=zipfile.ZIP_STORED
                z.writestr(info,data)
    stage=Path(evidence).resolve()/('archive-'+uuid.uuid4().hex);stage.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or set(names)!=set(content):raise ValueError('ARCHIVE_MEMBERS_MISMATCH')
        for name,data in content.items():
            actual=z.read(name)
            if actual!=data:raise ValueError('ARCHIVE_HASH_MISMATCH')
            path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(actual)
    version=subprocess.run([node,'-p','process.versions.node'],capture_output=True,text=True,check=True).stdout.strip()
    if int(version.split('.')[0])<20:raise ValueError('NODE_20_REQUIRED')
    for test in ['test/client.test.mjs','test/url-transport.test.mjs']:
        result=subprocess.run([node,str(stage/test)],capture_output=True,text=True,timeout=45)
        (stage/(Path(test).stem+'.txt')).write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode:raise ValueError('ARCHIVED_TEST_FAILED')
    receipt={'status':'PASS','sha256':sha(archive.read_bytes()),'members':len(content),'node':version,
             'transport_sha256':PIN,'archived_tests':11,'format':'ZIP_STORED/fixed-1980/0644/sorted'}
    (stage/'RECEIPT.json').write_text(json.dumps(receipt,indent=2))
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--evidence',required=True)
    p.add_argument('--source',default=str(SOURCE));p.add_argument('--node',default='node');p.add_argument('--build',action='store_true')
    a=p.parse_args();print(json.dumps(package(a.source,a.archive,a.evidence,a.node,a.build),indent=2))
