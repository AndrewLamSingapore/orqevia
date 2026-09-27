import json,os,pathlib,subprocess,time
base=pathlib.Path(__file__).resolve().parent
source=base/'execution-copy'
data=base/'python-data';data.mkdir(exist_ok=True)
tmp=base/'tmp';tmp.mkdir(exist_ok=True)
python=base/'venv/bin/python'
env={'PATH':str(base/'venv/bin')+os.pathsep+os.environ['PATH'],'HOME':str(data),'TMPDIR':str(tmp),'CI':'1','TZ':'UTC','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONPATH':str(base/'network-guard')+os.pathsep+str(source),'PRIME_DATA_DIR':str(data),'PRIME_COMPUTE_QUEUE_DB':str(data/'queue.db'),'PRIME_MEMORY_DB':str(data/'memory.db'),'PRIME_SPINE_DB':str(data/'spine.db'),'PRIME_COMPUTE_DB':str(data/'compute.db'),'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_TERMINAL_PROMPT':'0','GIT_ALLOW_PROTOCOL':'file','PRIME_PUBLIC_TRACE_RELAY_URL':'','PORTAL_BASE_URL':'','PORTFOLIO_RELAY_URL':'','OLLAMA_BASE_URL':'http://127.0.0.1:9'}
start=time.time()
command=[str(python),'-B','scripts/run_canonical_ci.py']
with (base/'canonical-regression.log').open('w') as log:
    result=subprocess.run(command,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600)
summary={'command':command,'exit_code':result.returncode,'elapsed_seconds':time.time()-start,'source_sha':'091e2f919edb1711b5a9e88404818095fa32b537','host':'Linux cloud, not physical Dell','network_boundary':'Python audit hook rejects IP socket.connect; Git protocols limited to file; credential-free allowlisted env; NOT kernel sandbox'}
(base/'canonical-run.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary))
print((base/'canonical-regression.log').read_text()[-9000:])
