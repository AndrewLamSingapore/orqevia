"""Resize the owner-approved original only. Pillow is a build tool, not runtime."""
from pathlib import Path
import argparse
import hashlib
import json

SOURCE_SHA256 = 'b3bdd53cc38b24c8be2896f1174b4d5f083be20f94f2042770224c72e2501844'
SOURCE_COMMIT = 'f03ce95d1752f316bca92257b0f7349a48863472'
SOURCE_PATH = 'assets/brands/orqevia/generated-original.png'
OUTPUTS = {192:'orqevia-official-v1-192.png',512:'orqevia-official-v1-512.png',
           180:'orqevia-official-v1-apple-touch.png',16:'orqevia-official-v1-favicon-16.png',
           32:'orqevia-official-v1-favicon-32.png',48:'orqevia-official-v1-favicon-48.png'}


def build(root: Path, *, check=False):
    import PIL
    from PIL import Image
    if PIL.__version__ != '12.3.0':
        raise RuntimeError('Use the recorded Pillow 12.3.0 build environment')
    raw = (root/SOURCE_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('Approved original logo bytes changed')
    image = Image.open(root/SOURCE_PATH)
    image.load()
    if image.size != (1254,1254) or image.mode != 'RGB':
        raise ValueError('Original dimensions, mode or opaque background changed')
    from io import BytesIO
    derivatives=[]
    for size,name in OUTPUTS.items():
        scaled=image.resize((size,size),resample=Image.Resampling.LANCZOS)
        buffer=BytesIO()
        scaled.save(buffer,format='PNG',compress_level=9,optimize=False)
        result=buffer.getvalue();target=root/'clients/pwa/icons'/name
        if check:
            if target.read_bytes()!=result:
                raise ValueError('Derived full-image bytes changed: '+name)
        else:
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result)
        derivatives.append({'path':str(target.relative_to(root)).replace('\\','/'),'size':[size,size],
                            'sha256':hashlib.sha256(result).hexdigest(),'bytes':len(result),'purpose':'any'})
    manifest={'schema':'orqevia.official-logo-provenance.v1','original':{'repository':'AndrewLamSingapore/orqevia',
        'branch':'brand-master-register-2026-10-10','commit':SOURCE_COMMIT,'path':SOURCE_PATH,
        'git_blob_sha1':'accb39978851a9c882fa31558412a15bffcfbfd2','sha256':SOURCE_SHA256,
        'bytes':len(raw),'size':[1254,1254],'mode':'RGB','opaque':True},
        'approval_reference':{'register_path':'governance/BRAND_MASTER_REGISTER.md',
            'register_commit':'f70f85ea547f1b2fa8f62e0d741344d4435df048',
            'original_upload_commit':SOURCE_COMMIT,
            'upload_note':'Owner-authored approved original binary upload follows the register; its older not-yet-uploaded sentence is historical.'},
        'derivation':{'pillow_version':PIL.__version__,'method':'FULL_IMAGE_RESIZE_LANCZOS',
            'color_mode':'original RGB','crop':False,'recolor':False,'redraw':False,
            'source_proportions_preserved':True,'source_opaque_background_preserved':True,
            'png_compress_level':9,'png_optimize':False,'maskable_claim':False},
        'derivatives':derivatives,'prior_generated_q_icons':'retained unreferenced compatibility/history; not official originals'}
    target=root/'assets/brands/orqevia/provenance.json'
    encoded=(json.dumps(manifest,indent=2,ensure_ascii=True)+'\n').encode()
    if check:
        if target.read_bytes()!=encoded:raise ValueError('Provenance manifest changed')
    else:target.write_bytes(encoded)
    print(json.dumps({'state':'PASS','check_only':check,'source_sha256':SOURCE_SHA256,'derivatives':derivatives}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    build(Path(__file__).resolve().parents[1],check=args.check)
