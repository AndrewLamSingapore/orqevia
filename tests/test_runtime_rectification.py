import json
from unittest.mock import patch

from app.answer_evaluator import evaluate_generated_answer
from app.compute_ledger import ComputeLedger
from app.hybrid_memory import HybridMemory
from app.memory import MemoryStore
from app.model_gateway import ModelResult
from app.settings import PrimeSettings


class Response:
    def __init__(self, payload): self.payload=payload
    def __enter__(self): return self
    def __exit__(self,*_): return False
    def read(self): return json.dumps(self.payload).encode()


def settings(tmp_path=None):
    return PrimeSettings('http://ollama:11434','gemma3:1b','gemma3:1b','embeddinggemma:300m-qat-q4_0',2)


def test_readiness_requires_every_exact_configured_model():
    with patch('urllib.request.urlopen',return_value=Response({'models':[{'name':'gemma3:1b'}]})):
        result=settings().ollama_readiness()
    assert result['ready'] is False
    assert result['missing_models']==['embeddinggemma:300m-qat-q4_0']


class EvalGateway:
    def __init__(self,text):self.text=text
    def local(self,**kwargs):return ModelResult(kwargs['task_id'],kwargs['stage'],'fake','evaluator',self.text,1,{})


def test_post_generation_gate_fails_closed_and_blocks_execution_claims():
    high=json.dumps({name:1 for name in ('source_coverage','supported_claims','contradiction_resistance','uncertainty_calibration','required_evidence','policy_conformance','task_success')})
    result=evaluate_generated_answer(gateway=EvalGateway(high),task_id='task',intent='send it',answer='PRIME sent the external message.',memory_context=[],portal_context=[],consequential=True)
    assert result['released'] is False
    assert result['scores']['policy_conformance']==0
    invalid=evaluate_generated_answer(gateway=EvalGateway('not json'),task_id='task',intent='answer',answer='draft',memory_context=[],portal_context=[])
    assert invalid['released'] is False and invalid['parse_error']=='ValueError'


class DeterministicHybrid(HybridMemory):
    def _embed(self,text):
        value=sum(ord(char) for char in text)
        return [float((value%17)+1),float((value%29)+1),float((value%43)+1)]


def test_embedding_index_is_persistent_and_versioned(tmp_path):
    store=MemoryStore(str(tmp_path/'memory.db'))
    store.record_episode(event_type='decision',content={'summary':'persistent semantic index'},source='test',salience=.9,durable_kind='decision',durable_key='semantic-index')
    store.consolidate()
    first=DeterministicHybrid(store,settings()).search('conceptually related retrieval')
    assert first and first[0]['retrieval_mode']=='persistent_hybrid'
    with store.connect() as db:
        row=db.execute('select model,dimensions from memory_embeddings').fetchone()
    assert row['model']=='embeddinggemma:300m-qat-q4_0' and row['dimensions']==3
    second=DeterministicHybrid(store,settings()).index_pending()
    assert second['indexed']==0
