from pathlib import Path
import subprocess,json,hashlib,time
base=Path(__file__).resolve().parent;s=(base/'run-canonical.py').read_text();ns={'__file__':str(base/'run-canonical.py')};exec(s[:s.index('start=time.time()')],ns)
source=ns['source'];env=ns['env'];python=ns['python']
commands=[('canonical',[str(python),'-B','scripts/run_canonical_ci.py']),('full-suite',[str(python),'-B','-m','pytest','-p','no:cacheprovider','-q','--basetemp',str(base/'full-suite-temp'),'--junitxml',str(base/'full-suite.xml'),'tests']),('node-regression',['node','--test',*[str(p.relative_to(source)) for p in sorted((source/'clients/pwa').glob('*tests.mjs'))],*[str(p.relative_to(source)) for p in sorted((source/'clients/dell/test').glob('*.test.mjs'))]]),('dell-packaging',[str(python),'-B','-m','unittest','discover','-s','clients/dell/tools','-p','test_package_client.py']),('provenance-reproduction',[str(python),'-B',str(base/'provenance-reproduction.py')])]
results=[]
for label,args in commands:
 start=time.time()
 with (base/(label+'.log')).open('x') as log:
  r=subprocess.run(args,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
 results.append({'label':label,'command':args,'exit_code':r.returncode,'seconds':time.time()-start})
 print(label,r.returncode,(base/(label+'.log')).read_text()[-450:],flush=True)
(base/'successor-runs.json').write_text(json.dumps(results,indent=2))
