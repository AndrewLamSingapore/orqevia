#!/usr/bin/env python3
import hashlib,json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

MODELS=['gemma3:1b','embeddinggemma:300m-qat-q4_0']

class Handler(BaseHTTPRequestHandler):
    def send_json(self,value,status=200):
        data=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path=='/api/tags':return self.send_json({'models':[{'name':name,'model':name} for name in MODELS]})
        return self.send_json({'error':'not_found'},404)
    def do_POST(self):
        size=int(self.headers.get('Content-Length','0'));body=json.loads(self.rfile.read(size) or b'{}')
        if self.path=='/api/embed':
            raw=str(body.get('input','')).encode();digest=hashlib.sha256(raw).digest();return self.send_json({'embeddings':[[round((byte+1)/256,6) for byte in digest[:16]]]})
        if self.path in {'/api/generate','/api/chat'}:
            prompt=str(body.get('prompt') or ((body.get('messages') or [{}])[-1].get('content')) or '')
            if 'PRIME EVALUATOR' in prompt:
                answer={name:.96 for name in ('source_coverage','supported_claims','contradiction_resistance','uncertainty_calibration','required_evidence','policy_conformance','task_success')};answer.update({'unsupported_claims':[],'contradictions':[],'evidence_gaps':[],'rationale':'Candidate is bounded and supported in the supplied acceptance fixture.'});text=json.dumps(answer)
            else:text='Bounded analysis based only on the supplied acceptance evidence. No external action was executed; uncertainty and evidence gaps remain explicit.'
            if self.path=='/api/chat':return self.send_json({'message':{'content':text},'prompt_eval_count':12,'eval_count':18})
            return self.send_json({'response':text,'prompt_eval_count':12,'eval_count':18})
        return self.send_json({'error':'not_found'},404)
    def log_message(self,*_):pass

ThreadingHTTPServer(('0.0.0.0',11434),Handler).serve_forever()
