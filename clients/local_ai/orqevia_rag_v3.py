"""Compatible internal V3 command, backed by the single shared service."""
import argparse,json,sys
from shared_client import SharedKnowledgeClient
def main():
    parser=argparse.ArgumentParser(description='ORQEVIA shared local RAG diagnostics; primary interface /pwa/')
    parser.add_argument('question',nargs='*');parser.add_argument('--top-k',type=int,default=3)
    parser.add_argument('--model',default='qwen2.5:7b');parser.add_argument('--retrieve-only',action='store_true')
    args=parser.parse_args()
    if args.model!='qwen2.5:7b':parser.error('The existing shared adapter uses qwen2.5:7b; no alternate model is silently substituted')
    question=' '.join(args.question).strip()
    if not question or not 1<=args.top_k<=5:parser.error('Supply a question and top-k between 1 and 5')
    try:result=SharedKnowledgeClient().call('retrieve' if args.retrieve_only else 'answer',{'question':question,'top_k':args.top_k})
    except Exception:sys.exit('Shared knowledge service unavailable or request rejected; original indexes preserved')
    print(json.dumps(result,indent=2,ensure_ascii=True))
if __name__=='__main__':main()
