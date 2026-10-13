from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pytest

from app.host_telemetry import host_metrics, SCHEMA, SPECS

NOW = '2026-10-13T10:00:00+00:00'


@pytest.fixture
def receipt(monkeypatch, tmp_path):
    path = tmp_path/'host.json'
    monkeypatch.setenv('PRIME_INTERFACE_HOST_TELEMETRY_RECEIPT', str(path))
    value = {'schema_version':SCHEMA,'source':{'system':'WINDOWS_HOST','instance':'ABEX','collector':'windows-cim-http-v1'},
             'collected_at_utc':NOW,'metrics':[{'metric_id':name,'unit':unit,'producer':producer,'scope':scope,
             'event_timestamp':NOW,'collection_status':'OBSERVED','value':0} for name,(unit,_,producer,scope) in SPECS.items()]}
    def write(candidate=value):
        path.write_text(json.dumps(candidate),encoding='utf-8')
        return host_metrics('ABEX',NOW)
    return path, value, write


def test_missing_or_unconfigured_receipt_does_not_invent_host_values(monkeypatch, receipt):
    assert all(row['producer']=='HOST_RECEIPT_MISSING' and row['value'] is None for row in host_metrics('ABEX',NOW))
    monkeypatch.delenv('PRIME_INTERFACE_HOST_TELEMETRY_RECEIPT')
    assert all(row['producer']=='HOST_COLLECTOR_NOT_CONFIGURED' for row in host_metrics('ABEX',NOW))


def test_measured_values_keep_exact_windows_scope_and_collection_time(receipt):
    _, value, write = receipt
    values = [100,51.25,0,34.125]
    for row, measurement in zip(value['metrics'],values): row['value']=measurement
    result = write()
    assert [row['value'] for row in result]==values
    assert all(row['source_system']=='WINDOWS_HOST' and row['source_instance']=='ABEX' and row['event_timestamp']==NOW for row in result)
    assert result[-1]['measurement_scope']=='LOCAL_LOOPBACK_HTTP_HEALTH'
    assert all(row['collection_status']=='OBSERVED' for row in result)


@pytest.mark.parametrize('change,code',[
    ({'schema_version':'other'},'HOST_RECEIPT_SCHEMA_MISMATCH'),
    ({'source':{'instance':'DELL'}},'HOST_RECEIPT_IDENTITY_MISMATCH'),
    ({'collected_at_utc':'2026-10-13T09:58:29Z'},'HOST_RECEIPT_STALE'),
    ({'collected_at_utc':'2026-10-13T10:00:06Z'},'HOST_RECEIPT_FUTURE'),
    ({'collected_at_utc':'2026-10-13T10:00:00'},'HOST_RECEIPT_INVALID'),
    ({'metrics':[{'metric_id':[]}]},'HOST_RECEIPT_INVALID'),
    ({'metrics':[]},'HOST_METRIC_MISSING'),
])
def test_wrong_identity_schema_time_or_shape_fails_closed(receipt,change,code):
    _, value, write = receipt
    value.update(change)
    assert all(row['value'] is None and row['producer']==code for row in write())


@pytest.mark.parametrize('value',[True,-1,101,float('nan'),float('inf'),None,'7',10**1000])
def test_invalid_percent_is_unavailable_without_suppressing_other_metrics(receipt,value):
    _, candidate, write = receipt
    candidate['metrics'][0]['value']=value
    result = write()
    assert result[0]['value'] is None and result[0]['producer']=='HOST_METRIC_INVALID'
    assert all(row['collection_status']=='OBSERVED' for row in result[1:])


@pytest.mark.parametrize('change',[
    {'unit':'bytes'}, {'scope':'GLOBAL_NETWORK'}, {'producer':'made-up'},
    {'event_timestamp':'2026-10-13T10:00:06Z'}, {'event_timestamp':'2026-10-13T09:59:00Z'},
    {'collection_status':'UNAVAILABLE','value':123,'failure_code':'COLLECTION_FAILED'},
    {'collection_status':'UNAVAILABLE','value':None,'failure_code':[]},
])
def test_metric_metadata_and_failures_cannot_claim_observed_values(receipt,change):
    _, value, write = receipt
    value['metrics'][-1].update(change)
    result=write()
    assert result[-1]['value'] is None and result[-1]['producer']=='HOST_METRIC_INVALID'
    assert result[0]['collection_status']=='OBSERVED'


def test_partial_failure_preserves_explicit_unavailability(receipt):
    _, value, write = receipt
    value['metrics'][-1].update(collection_status='UNAVAILABLE',value=None,failure_code='DEPENDENCY_UNAVAILABLE')
    result=write()
    assert result[-1]['value'] is None and result[-1]['producer']=='HOST_DEPENDENCY_UNAVAILABLE'
    assert result[0]['collection_status']=='OBSERVED'


@pytest.mark.parametrize('raw',[b'{"schema_version":',b'{"a":1,"a":2}',b'\x00'*10,b'x'*32769,b'['*1100+b']'*1100],ids=['torn','duplicate','null','oversized','recursive'])
def test_torn_oversized_duplicate_or_recursive_json_never_breaks_snapshot(receipt,raw):
    path,_,_=receipt
    path.write_bytes(raw)
    assert all(row['value'] is None and row['producer'] in {'HOST_RECEIPT_INVALID','HOST_RECEIPT_SCHEMA_MISMATCH'} for row in host_metrics('ABEX',NOW))


def test_same_reader_is_used_by_public_aggregate_snapshot(monkeypatch,receipt,tmp_path):
    from app.interface_telemetry import snapshot
    _,value,write=receipt
    value['collected_at_utc']=datetime.now(timezone.utc).isoformat()
    for row in value['metrics']: row['event_timestamp']=value['collected_at_utc']
    write()
    monkeypatch.setenv('PRIME_INTERFACE_HOST_ID','ABEX')
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path))
    report=snapshot('fixture','MEMBER')
    metrics={row['metric_id']:row for row in report['metrics']}
    assert metrics['cpu']['collection_status']=='OBSERVED'
    assert metrics['network_latency']['measurement_scope']=='LOCAL_LOOPBACK_HTTP_HEALTH'
    assert report['ready_agent_count'] is None


@pytest.mark.skipif(os.name!='nt',reason='Windows CIM sampler integration')
def test_windows_sampler_atomic_replacement_and_truthful_partial_failures(monkeypatch,tmp_path):
    script=Path(__file__).parents[1]/'scripts/collect_abex_host_telemetry.ps1'
    output=tmp_path/'receipt.json'
    command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-OutputPath',str(output),'-HostId','ABEX']
    for _ in range(2):
        completed=subprocess.run(command,capture_output=True,text=True,timeout=25)
        assert completed.returncode==0,completed.stderr
        value=json.loads(output.read_text(encoding='utf-8'))
        assert value['schema_version']==SCHEMA and value['source']['instance']=='ABEX'
        assert len(value['metrics'])==4
        for row in value['metrics']:
            if row['collection_status']=='OBSERVED': assert isinstance(row['value'],(int,float)) and 0<=row['value']<=SPECS[row['metric_id']][1]
            else: assert row['value'] is None and row['failure_code'] in {'COLLECTION_FAILED','DEPENDENCY_UNAVAILABLE','HTTP_UNHEALTHY','INVALID_SAMPLE'}
        monkeypatch.setenv('PRIME_INTERFACE_HOST_TELEMETRY_RECEIPT',str(output))
        observed=host_metrics('ABEX',datetime.now(timezone.utc).isoformat())
        assert len(observed)==4
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.skipif(os.name!='nt',reason='Windows mocked CIM sampler integration')
def test_malformed_cpu_components_cannot_average_into_valid_load(tmp_path):
    script=str(Path(__file__).parents[1]/'scripts/collect_abex_host_telemetry.ps1').replace("'","''")
    output=tmp_path/'fixture.json'
    destination=str(output).replace("'","''")
    # Synthetic fixture only: +100 and -100 would incorrectly average to0 without component validation.
    source="""function Get-CimInstance { param($ClassName,$OperationTimeoutSec,$Filter)
if ($ClassName -eq 'Win32_Processor') { [pscustomobject]@{LoadPercentage=100;NumberOfLogicalProcessors=1}; [pscustomobject]@{LoadPercentage=-100;NumberOfLogicalProcessors=1} }
else { throw 'DEPENDENCY_UNAVAILABLE' } }
& '"""+script+"' -HostId ABEX -OutputPath '"+destination+"'"
    completed=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-Command',source],capture_output=True,text=True,timeout=15)
    assert completed.returncode==0,completed.stderr
    value=json.loads(output.read_text(encoding='utf-8'))
    cpu=next(row for row in value['metrics'] if row['metric_id']=='cpu')
    assert cpu['value'] is None and cpu['failure_code']=='INVALID_SAMPLE'
