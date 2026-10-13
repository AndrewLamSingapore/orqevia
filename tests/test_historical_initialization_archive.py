"""Historical raw-blob archive custody; no oracle, signing or runtime calls."""
import ast
import hashlib
import io
import subprocess
import tarfile

from tests import historical_initialization_fixture as fixture


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def archive_files(raw):
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as source:
        return {member.name: source.extractfile(member).read()
                for member in source.getmembers() if member.isfile()}


def test_historical_archive_preserves_all_47_blobs_under_windows_git_settings(tmp_path):
    # Use the original frozen closure and its historical attributes, not current
    # checkout bytes or altered reviewer/oracle inputs.
    verifier = ast.parse(git(fixture.ROOT, 'show',
                            fixture.REVISION + ':scripts/sign_admitted_agent_cases.py'))
    paths = next(ast.literal_eval(node.value) for node in verifier.body
                 if isinstance(node, ast.Assign) and any(
                     isinstance(target, ast.Name) and target.id == 'CODE_FILES'
                     for target in node.targets))
    assert len(paths) == 47
    original = {path: git(fixture.ROOT, 'show', fixture.REVISION + ':' + path)
                for path in paths}
    repository = tmp_path / 'source'
    repository.mkdir()
    git(repository, 'init', '--quiet')
    git(repository, 'config', 'user.name', 'Historical archive source test')
    git(repository, 'config', 'user.email', 'archive-custody@example.invalid')
    git(repository, 'config', 'core.autocrlf', 'false')
    git(repository, 'config', 'core.eol', 'lf')
    for path, raw in original.items():
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (repository / '.gitattributes').write_bytes(
        git(fixture.ROOT, 'show', fixture.REVISION + ':.gitattributes'))
    git(repository, 'add', '--all')
    git(repository, 'commit', '--quiet', '-m', 'Frozen archive custody source test')
    revision = git(repository, 'rev-parse', 'HEAD').decode().strip()
    git(repository, 'config', 'core.autocrlf', 'true')
    git(repository, 'config', 'core.eol', 'crlf')

    # Negative control proves the old archive command detects the actual fault.
    converted = archive_files(git(repository, 'archive', '--format=tar', revision))
    mismatched = [path for path, raw in original.items() if converted[path] != raw]
    assert len(mismatched) == 46
    assert all(converted[path].replace(b'\r\n', b'\n') == original[path]
               for path in mismatched)

    preserved = archive_files(fixture._historical_source_archive(repository, revision))
    assert all(preserved[path] == raw for path, raw in original.items())
    assert all(hashlib.sha256(preserved[path]).digest() == hashlib.sha256(raw).digest()
               for path, raw in original.items())
    # The fix is command-scoped and does not alter the caller's Git settings.
    assert git(repository, 'config', '--get', 'core.autocrlf').strip() == b'true'
    assert git(repository, 'config', '--get', 'core.eol').strip() == b'crlf'
