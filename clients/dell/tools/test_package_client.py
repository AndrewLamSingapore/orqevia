import shutil
import unittest
import uuid
import zipfile
from package_client import SOURCE,package

class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.root=SOURCE/'build'/uuid.uuid4().hex;self.root.mkdir(parents=True)
    def test_reproducible_and_exclusive(self):
        a=self.root/'a.zip';b=self.root/'b.zip'
        one=package(SOURCE,a,self.root,build=True)
        two=package(SOURCE,b,self.root,build=True)
        self.assertEqual(one['sha256'],two['sha256']);self.assertEqual(a.read_bytes(),b.read_bytes())
        with self.assertRaises(FileExistsError):package(SOURCE,a,self.root,build=True)
    def test_stale_transport_denied(self):
        copy=self.root/'source';shutil.copytree(SOURCE,copy,ignore=shutil.ignore_patterns('build'))
        (copy/'lib/upstream.mjs').write_text('unapproved stale transport')
        with self.assertRaisesRegex(ValueError,'UNAPPROVED_TRANSPORT'):package(copy,self.root/'no.zip',self.root,build=True)
        self.assertFalse((self.root/'no.zip').exists())
    def test_tampered_archive_denied(self):
        good=self.root/'good.zip';bad=self.root/'bad.zip';package(SOURCE,good,self.root,build=True)
        with zipfile.ZipFile(good) as src,zipfile.ZipFile(bad,'x') as dst:
            for name in src.namelist():dst.writestr(name,b'changed' if name=='lib/upstream.mjs' else src.read(name))
        with self.assertRaisesRegex(ValueError,'ARCHIVE_HASH_MISMATCH'):package(SOURCE,bad,self.root)

if __name__=='__main__':unittest.main()
