"""Disposable repositories containing code only, never production records."""
from pathlib import Path
import shutil
import subprocess

import publish


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), '-c', 'user.name=Test',
                                   '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false',
                                   '-c', 'core.hooksPath=/dev/null', *args], stderr=subprocess.PIPE).decode().strip()


def commit(source):
    git(source.parent, 'add', '--', 'workflow')
    git(source.parent, 'commit', '-q', '-m', 'Synthetic runtime fixture')
    return git(source.parent, 'rev-parse', 'HEAD')


def initialize(source):
    git(source.parent, 'init', '-q')
    return commit(source)


def copy_source(root):
    source = Path(root) / 'workflow'
    source.mkdir()
    for name in publish.FILES:
        shutil.copy2(publish.SOURCE / name, source / name)
    revision = initialize(source)
    return source, revision


def bump(source, before, after):
    for name in ['curriculum.yaml', 'pyproject.toml', 'uv.lock', 'COACH.md']:
        path = source / name
        path.write_text(path.read_text().replace(before, after))
    return commit(source)
