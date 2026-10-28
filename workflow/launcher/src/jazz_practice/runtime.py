"""Materialize a pinned Git commit into a disposable local runtime cache."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

REQUIRED = ['review.py', 'COACH.md', 'curriculum.yaml', 'pyproject.toml', 'uv.lock']
WEB = ['webapp.py', 'sessions.py', 'webapp.html', 'webapp.css', 'webapp.js', 'audio.mjs', 'capture.mjs']
LOCALIZATION = ['i18n.mjs', 'translations.json']
NOTATION = ['notation.py', 'score.mjs', 'timeline.mjs', 'Bravura.woff2', 'Bravura-LICENSE.txt', 'THIRD_PARTY.md']
RECOMMENDATION = ['recommendation.py', 'recommendation.schema.json']
FILES = REQUIRED + WEB + LOCALIZATION + NOTATION + RECOMMENDATION
PIN = 'runtime.json'
CACHE = '.runtime'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True)
    require(result.returncode == 0, 'Git 커밋을 읽을 수 없습니다. 로컬 저장소와 지정한 ref를 확인하세요.')
    return result.stdout


def repository(path):
    return Path(git(path, 'rev-parse', '--show-toplevel').decode().strip())


def resolve(repo, ref):
    require(isinstance(ref, str) and ref and not ref.startswith('-') and '\n' not in ref,
            '잘못된 Git ref입니다.')
    revision = git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    require(bool(re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', revision)), '잘못된 Git commit입니다.')
    return revision


def snapshot(repo, ref):
    revision = resolve(repo, ref)
    names = git(repo, 'ls-tree', '--name-only', revision + ':workflow').decode().splitlines()
    require(set(REQUIRED) <= set(names), '커밋에 실행 소스가 없습니다.')
    require(not set(WEB).intersection(names) or set(WEB) <= set(names), '웹 실행 파일이 누락되었습니다.')
    require(not set(LOCALIZATION).intersection(names) or set(LOCALIZATION) <= set(names),
            'Runtime localization files are incomplete.')
    require(not set(NOTATION).intersection(names) or set(NOTATION) <= set(names),
            'Runtime notation files are incomplete.')
    require(not set(RECOMMENDATION).intersection(names) or set(RECOMMENDATION) <= set(names),
            'Runtime recommendation files are incomplete.')
    contents = {name: git(repo, 'show', f'{revision}:workflow/{name}') for name in FILES if name in names}
    version = tomllib.loads(contents['pyproject.toml'].decode())['project']['version']
    manifest = {'revision': revision, 'version': version,
                'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    return manifest, contents


def atomic_text(path, text):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.runtime-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def lock(root):
    with (root / '.practice.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def read_pin(root):
    path = root / PIN
    if not path.exists():
        return None
    pin = json.loads(path.read_text())
    require(isinstance(pin, dict) and pin.get('schema_version') == 1
            and isinstance(pin.get('revision'), str)
            and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', pin['revision'])
            and isinstance(pin.get('version'), str), 'runtime.json 형식이 잘못되었습니다.')
    return pin


def activate(root, manifest):
    # Keep the version marker for Git snapshots of older runtimes that read it.
    atomic_text(root / 'active-version', manifest['version'] + '\n')
    pin = {key: manifest[key] for key in ['revision', 'version']}
    atomic_text(root / PIN, json.dumps({'schema_version': 1, **pin}, indent=2) + '\n')


def materialize(root, manifest, contents):
    cache = root / CACHE
    cache.mkdir(exist_ok=True)
    destination = cache / manifest['revision']
    if not destination.exists():
        temporary = Path(tempfile.mkdtemp(prefix='.install-', dir=cache))
        try:
            for name, data in contents.items():
                (temporary / name).write_bytes(data)
            (temporary / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            os.rename(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    require(not destination.is_symlink(), '실행 캐시 경로가 변경되었습니다.')
    marker = destination / 'manifest.json'
    require(marker.is_file() and not marker.is_symlink()
            and json.loads(marker.read_text()) == manifest,
            '실행 캐시 정보가 변경되었습니다. 해당 캐시를 삭제한 뒤 다시 실행하세요.')
    require(all((destination / name).is_file() and not (destination / name).is_symlink()
                and hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
                for name, digest in manifest['sha256'].items()),
            '실행 캐시가 수정되었습니다. 해당 캐시를 삭제한 뒤 다시 실행하세요.')
    return destination


def selected(root):
    repo = repository(root)
    with lock(root):
        pin = read_pin(root)
        if pin is None:
            require(not (root / 'active-version').exists() and not (root / 'practice.csv').exists(),
                    '기존 연습의 runtime.json이 없습니다. 백업을 복원하거나 workflow에서 기존 커밋을 지정해 이관하세요.')
            ref = (root / 'runtime-ref').read_text().strip()
        else:
            ref = pin['revision']
        manifest, contents = snapshot(repo, ref)
        require(pin is None or pin['version'] == manifest['version'], '고정된 커밋과 버전이 다릅니다.')
        destination = materialize(root, manifest, contents)
        if pin is None:
            activate(root, manifest)
        elif not (root / 'active-version').exists() or (root / 'active-version').read_text().strip() != pin['version']:
            atomic_text(root / 'active-version', pin['version'] + '\n')
    return destination, manifest


def run(root, args):
    try:
        destination, manifest = selected(root)
        if args == ['runtime']:
            print(json.dumps({'version': manifest['version'], 'revision': manifest['revision'],
                              'cache': str(destination.relative_to(root))}, indent=2))
            return 0
        require(args[:1] != ['serve'] or (destination / 'webapp.py').is_file(),
                f"활성 런타임 {manifest['version']}은 웹을 지원하지 않습니다. "
                '미완료 과제를 정리한 뒤 workflow의 publish.py로 웹 지원 Git ref를 활성화하세요.')
        uv = shutil.which('uv')
        require(uv, 'uv 실행 파일이 필요합니다.')
        os.environ.pop('VIRTUAL_ENV', None)
        os.environ.pop('UV_PROJECT_ENVIRONMENT', None)
        os.execv(uv, [uv, 'run', '--quiet', '--frozen', '--project', str(destination),
                     'python', str(destination / 'review.py'), '--practice-root', str(root), *args])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'오류: {exc}', file=sys.stderr)
        return 2
