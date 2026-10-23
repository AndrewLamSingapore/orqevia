"""Real FAISS persistence/extraction checks with deterministic embedding fixture.

Real cached HF embedding and Qwen generation have separate runtime receipts.
"""
import json
from pathlib import Path
import pytest
faiss=pytest.importorskip('faiss')
import numpy as np
from app.local_knowledge import KnowledgeEngine,sha

class Encoder:
    def encode(self,texts,**kwargs):
        # Deliberately separable directions for source-isolation regression.
        return np.asarray([[1.,0.] if 'alpha' in t.lower() else [0.,1.] for t in texts],dtype='float32')

@pytest.fixture
def engine(tmp_path):
    (tmp_path/'documents').mkdir();(tmp_path/'rag_index_v2').mkdir()
    raw=b'Alpha reference states the access token expires after ninety days.'
    (tmp_path/'documents'/'alpha.txt').write_bytes(raw)
    record={'source':'alpha.txt','page':None,'text':raw.decode(),'sha256':sha(raw)}
    (tmp_path/'rag_index_v2'/'chunks.json').write_text(json.dumps([record]))
    index=faiss.IndexFlatIP(2);index.add(np.asarray([[1.,0.]],dtype='float32'));faiss.write_index(index,str(tmp_path/'rag_index_v2'/'index.faiss'))
    return KnowledgeEngine(tmp_path,encoder=Encoder(),generator=lambda prompt:'The access token lasts ninety days [1].')

def test_preserved_index_retrieval_and_grounded_generation(engine):
    found=engine.retrieve('alpha access')
    assert found['results'][0]['source']=='alpha.txt' and found['results'][0]['similarity']==1
    generated=engine.answer('alpha access')
    assert generated['model_invoked'] and generated['citations_valid']
    assert generated['status']=='CITED_MODEL_INTERPRETATION'


def test_fresh_private_store_reads_empty_and_first_ingest_persists(tmp_path):
    fresh=KnowledgeEngine(tmp_path,encoder=Encoder())
    assert fresh.list_documents()=={'documents':[]}
    assert fresh.health()['index']['chunks']==0
    assert fresh.retrieve('alpha')['status']=='NO_EVIDENCE'
    assert fresh.reindex()['status']=='EMPTY'
    assert not list(tmp_path.iterdir()), 'Empty observations must not initialize persistent data'
    result=fresh.ingest('alpha.txt',b'Alpha is the sole first document in this isolated fixture.')
    assert result['status']=='INDEXED'
    reopened=KnowledgeEngine(tmp_path,encoder=Encoder())
    assert len(reopened.list_documents()['documents'])==1
    assert reopened.retrieve('alpha')['results'][0]['document_id']==result['document_id']


def test_partial_index_is_not_silently_replaced_with_empty_store(tmp_path):
    (tmp_path/'rag_index_v2').mkdir()
    (tmp_path/'rag_index_v2'/'chunks.json').write_text('[]')
    fresh=KnowledgeEngine(tmp_path,encoder=Encoder())
    with pytest.raises((RuntimeError,OSError)):
        fresh.list_documents()
    assert not (tmp_path/'rag_index_v2'/'CURRENT.json').exists()

def test_ingest_duplicate_restart_and_source_isolation(engine):
    result=engine.ingest('beta.txt',b'Beta reference records a completely different subject.')
    assert result['status']=='INDEXED'
    assert engine.ingest('renamed.txt',b'Beta reference records a completely different subject.')['duplicate_prevented']
    reopened=KnowledgeEngine(engine.root,encoder=Encoder())
    assert reopened.health()['index']['chunks']==2
    hits=reopened.retrieve('beta',document_ids=[result['document_id']])['results']
    assert hits and all(h['source']=='beta.txt' for h in hits)
    assert (engine.store/'index.faiss').is_file() and (engine.store/'CURRENT.json').is_file()

def test_document_update_excludes_superseded_version(engine):
    first=engine.ingest('beta.txt',b'Beta first version.')
    second=engine.ingest('beta.txt',b'Beta revised version.')
    assert second['version']==2
    assert engine.retrieve('beta',document_ids=[first['document_id']])['status']=='NO_EVIDENCE'
    assert engine.retrieve('beta',document_ids=[second['document_id']])['results'][0]['document_version']==2

def test_reindex_and_failed_pointer_commit_preserve_previous_generation(engine,monkeypatch):
    import app.local_knowledge as module
    engine.ingest('beta.txt',b'Beta retained evidence.')
    previous=(engine.store/'CURRENT.json').read_bytes()
    original=module.atomic_json
    def failed(path,value):
        if Path(path).name=='CURRENT.json':raise OSError('controlled pointer failure')
        return original(path,value)
    monkeypatch.setattr(module,'atomic_json',failed)
    with pytest.raises(OSError):engine.reindex()
    assert (engine.store/'CURRENT.json').read_bytes()==previous
    assert KnowledgeEngine(engine.root,encoder=Encoder()).health()['index']['chunks']==2

def test_invalid_documents_and_unknown_citations_fail_explicitly(engine):
    with pytest.raises(ValueError):engine.ingest('../escape.txt',b'bad')
    with pytest.raises(ValueError):engine.ingest('code.exe',b'bad')
    engine.generator=lambda prompt:'Unsupported claim [99]'
    assert engine.answer('alpha access')['citations_valid'] is False

def test_pdf_and_docx_extraction(engine,tmp_path):
    from pypdf import PdfWriter
    writer=PdfWriter();writer.add_blank_page(width=300,height=300)
    blank=tmp_path/'blank.pdf'
    with blank.open('wb') as f:writer.write(f)
    with pytest.raises(ValueError):engine.ingest('blank.pdf',blank.read_bytes())
    from pypdf.generic import DecodedStreamObject,DictionaryObject,NameObject
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page=writer.pages[0]
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 200 Td (Beta PDF extraction fixture.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    with blank.open('wb') as f:writer.write(f)
    assert engine.ingest('actual-text.pdf',blank.read_bytes())['status']=='INDEXED'
    from docx import Document
    doc=Document();doc.add_paragraph('Beta DOCX actual extraction fixture.');path=tmp_path/'sample.docx';doc.save(path)
    assert engine.ingest('sample.docx',path.read_bytes())['status']=='INDEXED'
