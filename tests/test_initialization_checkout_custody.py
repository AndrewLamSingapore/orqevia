"""Real Git checkout discriminator; public source test, never certification."""
import ast
from pathlib import Path
import subprocess

from scripts.audit_initialization_package import MAIN, ROOT



def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def test_autocrlf_checkout_preserves_all_47_protected_git_blob_bytes(tmp_path):
    # Construct an actual minimal repository from the authoritative Git blobs,
    # not local source bytes or synthetic oracle evidence.
    repository=tmp_path/'source'
    repository.mkdir()
    git(repository,'init','--quiet')
    git(repository,'config','user.name','Source custody test')
    git(repository,'config','user.email','source-custody@example.invalid')
    git(repository,'config','core.autocrlf','false')
    historical=ast.parse(git(ROOT,'show',MAIN+':scripts/sign_admitted_agent_cases.py').decode())
    assignments=[node for node in historical.body if isinstance(node,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=='CODE_FILES' for target in node.targets)]
    assert len(assignments)==1
    code_files=ast.literal_eval(assignments[0].value)
    assert type(code_files) is tuple and len(set(code_files))==47
    original={path:git(ROOT,'show',MAIN+':'+path) for path in code_files}
    assert len(original)==47
    for path,raw in original.items():
        target=repository/path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
    git(repository,'add','--all')
    git(repository,'commit','--quiet','-m','Unnormalized closure source test')
    baseline=git(repository,'rev-parse','HEAD').decode().strip()
    (repository/'.gitattributes').write_bytes((ROOT/'.gitattributes').read_bytes())
    git(repository,'add','.gitattributes')
    git(repository,'commit','--quiet','-m','Exact blob custody source test')
    repaired=git(repository,'rev-parse','HEAD').decode().strip()
    checkout=tmp_path/'checkout'
    subprocess.run(['git','-c','core.autocrlf=true','clone','--quiet','--no-checkout',
                    str(repository),str(checkout)],check=True,
                   stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    git(checkout,'config','core.autocrlf','true')
    git(checkout,'checkout','--quiet',baseline)
    mismatched=[path for path,raw in original.items() if (checkout/path).read_bytes()!=raw]
    # Prove this test detects the actual Windows failure mechanism.
    assert mismatched
    # A fresh checkout must materialize after reading the repaired attributes.
    # Switching only the attributes commit leaves unchanged cached files alone.
    git(checkout,'read-tree','--empty')
    git(checkout,'checkout','--quiet','--force',repaired)
    for path,raw in original.items():
        assert (checkout/path).read_bytes()==raw,path
        assert git(checkout,'show',repaired+':'+path)==raw,path
