"""Lazy, local source cache and bounded retrieval shared by web and coaching CLI.

Catalog entries are links, not a recommendation curriculum. FTS searches cached
content; a missing cache is acquired only after a source is requested. Structural
music validity and fidelity to a published example are separate checks.
"""
from __future__ import annotations

import contextlib
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / 'materials-catalog.json').read_text())
MAX_DOWNLOAD = 40_000_000
MAX_EXCERPTS = 3
MAX_IMAGES = 3
EXCERPT_CHARS = 2200


class MaterialError(ValueError):
    pass


def sha(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def catalog():
    return copy.deepcopy(CATALOG['sources'])


def planning_catalog():
    # The goal-selection call needs topics and stable IDs, not repeated full URLs.
    return [{k: source[k] for k in ('id', 'title', 'publisher', 'format', 'topics')} for source in catalog()]


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise MaterialError('Only public HTTPS source URLs are supported.')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise MaterialError('The source hostname could not be resolved.') from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise MaterialError('The source resolved to a non-public address.')


class PublicRedirect(HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, headers, deadline):
    public_url(url)
    request = Request(url, headers={'User-Agent': 'MyJazzTutor/1.0 (local learning material cache)', **headers})
    try:
        response = build_opener(PublicRedirect()).open(request, timeout=min(15, max(1, deadline - time.monotonic())))
        with response:
            if int(response.headers.get('Content-Length', '0')) > MAX_DOWNLOAD:
                raise MaterialError('Source exceeds the 40 MB download limit.')
            chunks, size = [], 0
            while True:
                if time.monotonic() >= deadline:
                    raise MaterialError('Source download timed out.')
                block = response.read(65536)
                if not block:
                    break
                size += len(block)
                if size > MAX_DOWNLOAD:
                    raise MaterialError('Source exceeds the 40 MB download limit.')
                chunks.append(block)
            return {'status': response.status, 'url': response.url,
                    'headers': dict(response.headers.items()), 'body': b''.join(chunks)}
    except HTTPError as exc:
        if exc.code == 304:
            return {'status': 304}
        raise MaterialError(f'Source returned HTTP {exc.code}.') from None
    except (OSError, URLError, ValueError) as exc:
        raise MaterialError('Source could not be downloaded.') from exc


class Sections(HTMLParser):
    """Readable text with headings; images are not represented as read score notes."""
    IGNORED = {'script', 'style', 'nav', 'footer', 'header', 'noscript', 'svg', 'form'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = []
        self.heading = None
        self.heading_parts = []
        self.title = 'Introduction'
        self.parts = []
        self.sections = []

    def flush(self):
        text = re.sub(r'[ \t]+', ' ', ''.join(self.parts))
        text = re.sub(r'\n\s*\n+', '\n\n', text).strip()
        if text:
            self.sections.append((self.title, text))
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORED:
            self.ignored.append(tag)
        if self.ignored:
            return
        if re.fullmatch('h[1-6]', tag):
            self.flush()
            self.heading, self.heading_parts = tag, []
        if tag in ('p', 'br', 'li', 'div'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag == self.heading:
            self.title = ' '.join(''.join(self.heading_parts).split())[:200] or self.title
            self.heading = None
        if tag in ('p', 'li', 'div'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.ignored:
            (self.heading_parts if self.heading else self.parts).append(data)


class MaterialStore:
    def __init__(self, root=None, sources=None, fetcher=None):
        base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'my-jazz-tutor' / 'materials'
        self.root = Path(root or os.environ.get('JAZZ_MATERIALS_CACHE', base))
        self.sources = {s['id']: copy.deepcopy(s) for s in (sources if sources is not None else catalog())}
        self.fetcher = fetcher or download

    @contextlib.contextmanager
    def lock(self, source_id, deadline):
        (self.root / 'locks').mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / 'locks' / (source_id + '.lock')).open('a') as lock:
            while True:
                if time.monotonic() >= deadline:
                    raise MaterialError('Source cache was busy beyond the request time limit.')
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(min(.05, max(0, deadline - time.monotonic())))
            yield

    def source(self, source_id):
        if source_id not in self.sources or not re.fullmatch(r'[a-z0-9-]{1,80}', source_id):
            raise MaterialError('Unknown material source ID.')
        return self.sources[source_id]

    def fetch(self, source_id, *, refresh=False, deadline=None):
        source = self.source(source_id)
        deadline = deadline or time.monotonic() + 45
        with self.lock(source_id, deadline):
            manifest_path = self.root / 'sources' / (source_id + '.json')
            old = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
            valid = False
            if old:
                original = self.root / 'objects' / old['sha256'] / 'original'
                valid = original.is_file() and sha(original.read_bytes()) == old['sha256']
            if valid and not refresh:
                return old
            headers = {}
            if valid:
                if old.get('etag'):
                    headers['If-None-Match'] = old['etag']
                if old.get('last_modified'):
                    headers['If-Modified-Since'] = old['last_modified']
            response = self.fetcher(source['url'], headers, deadline)
            if response['status'] == 304 and valid:
                return old
            body = response.get('body', b'')
            if response['status'] != 200 or not body or len(body) > MAX_DOWNLOAD:
                raise MaterialError('Source download was empty, incomplete or oversized.')
            if source['format'] == 'pdf' and not body.startswith(b'%PDF-'):
                raise MaterialError('The source did not return a PDF.')
            content_hash = sha(body)
            metadata = {k.lower(): v for k, v in response.get('headers', {}).items()}
            manifest = {**source, 'resolved_url': response.get('url', source['url']), 'sha256': content_hash,
                        'retrieved_at': datetime.now(timezone.utc).isoformat(),
                        'etag': metadata.get('etag'), 'last_modified': metadata.get('last-modified'),
                        'media_type': metadata.get('content-type', source['format'])}
            atomic(self.root / 'objects' / content_hash / 'original', body)
            atomic(manifest_path, encoded(manifest))
            return manifest

    def _pdf(self, manifest, pages, deadline):
        directory = self.root / 'objects' / manifest['sha256']
        target = directory / 'text.json'
        if target.exists() and all((directory / f'page-{p}.png').exists() for p in pages):
            return json.loads(target.read_text())
        with tempfile.TemporaryDirectory(prefix='extract-', dir=directory) as temp:
            output = Path(temp) / 'text.json'
            try:
                process = subprocess.run([sys.executable, str(HERE / 'material_extract.py'), str(directory / 'original'),
                                          str(output), json.dumps(pages)], stdout=subprocess.DEVNULL,
                                         stderr=subprocess.PIPE, timeout=max(.1, min(30, deadline - time.monotonic())))
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise MaterialError('PDF extraction timed out or could not start.') from exc
            if process.returncode or not output.exists() or output.stat().st_size > 8_000_000:
                raise MaterialError('PDF extraction failed. The source has not been read.')
            result = json.loads(output.read_text())
            if any(not 1 <= p <= result['page_count'] for p in pages):
                raise MaterialError('Requested PDF page does not exist.')
            for page in pages:
                image = Path(temp) / f'page-{page}.png'
                if not image.exists() or image.stat().st_size > 3_000_000:
                    raise MaterialError('PDF page image exceeds the image limit.')
                atomic(directory / image.name, image.read_bytes())
            atomic(target, encoded(result))
            return result

    def extract(self, manifest, *, pages=(), deadline=None):
        self.source(manifest['id'])
        deadline = deadline or time.monotonic() + 40
        with self.lock(manifest['id'], deadline):
            directory = self.root / 'objects' / manifest['sha256']
            target = directory / 'text.json'
            if manifest['format'] == 'pdf':
                result = self._pdf(manifest, pages, deadline)
            elif target.exists():
                result = json.loads(target.read_text())
            else:
                raw = (directory / 'original').read_bytes().decode('utf-8', errors='replace')
                if manifest['format'] == 'html':
                    parser = Sections()
                    parser.feed(raw[:4_000_000]); parser.flush()
                    sections = parser.sections
                else:
                    sections = [('Source notation', raw)]
                chunks = []
                remaining = 500_000
                for number, (heading, text) in enumerate(sections):
                    bounded = text[:min(14000, remaining)]
                    remaining -= len(bounded)
                    if bounded:
                        chunks.append({'locator': {'kind': 'section', 'section': str(number + 1), 'label': heading},
                                       'text': bounded, 'truncated': len(bounded) < len(text)})
                result = {'extractor': 'readable-sections-1', 'chunks': chunks}
                atomic(target, encoded(result))
            with self.database() as db:
                db.execute('DELETE FROM excerpts WHERE source_id=? AND content_hash=?', (manifest['id'], manifest['sha256']))
                for index, chunk in enumerate(result['chunks']):
                    db.execute('INSERT INTO excerpts VALUES (?,?,?,?,?)',
                               (manifest['id'], manifest['sha256'], index, chunk['locator']['label'], chunk['text']))
            return result

    @contextlib.contextmanager
    def database(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(self.root / 'search.sqlite3', timeout=10)
        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS excerpts USING fts5(source_id UNINDEXED, content_hash UNINDEXED, chunk_index UNINDEXED, title, text)')
        try:
            with db:
                yield db
        finally:
            db.close()

    def retrieve(self, requests, *, deadline=None):
        if not isinstance(requests, list) or len(requests) > 2:
            raise MaterialError('At most two sources can be requested.')
        deadline = deadline or time.monotonic() + 90
        packets, images, failures = [], [], []
        for request in requests:
            source_id = request['source_id']
            self.source(source_id)  # Invented IDs are a contract error, never a network fallback.
            if len(packets) >= MAX_EXCERPTS:
                break
            try:
                manifest = self.fetch(source_id, deadline=deadline)
                pages = request.get('pages', [])
                if pages and manifest['format'] != 'pdf':
                    raise MaterialError('Page numbers are only supported for PDFs.')
                if any(type(p) is not int or not 1 <= p <= 300 for p in pages) or len(pages) > 2:
                    raise MaterialError('At most two PDF pages per source can be requested.')
                document = self.extract(manifest, deadline=deadline)
                if pages:
                    selected = [p - 1 for p in dict.fromkeys(pages)]
                    if any(p >= len(document['chunks']) for p in selected):
                        raise MaterialError('Requested PDF page does not exist.')
                else:
                    terms = re.findall(r'[\w-]{2,40}', request.get('query', ''), flags=re.UNICODE)[:12]
                    query = ' OR '.join('"' + term.replace('"', '') + '"' for term in terms)
                    with self.database() as db:
                        rows = db.execute('SELECT chunk_index FROM excerpts WHERE excerpts MATCH ? AND source_id=? AND content_hash=? ORDER BY rank LIMIT 2',
                                          (query or '"piano"', source_id, manifest['sha256'])).fetchall()
                    selected = [int(row[0]) for row in rows] or list(range(min(1, len(document['chunks']))))
                selected = selected[:MAX_EXCERPTS - len(packets)]
                if manifest['format'] == 'pdf':
                    self.extract(manifest, pages=[p + 1 for p in selected], deadline=deadline)
                for index in selected:
                    chunk = document['chunks'][index]
                    locator = chunk['locator']
                    excerpt_id = 'M-' + sha(encoded([source_id, manifest['sha256'], locator]))[:24]
                    text = chunk['text']
                    # Search may hit late in a long section; keep a bounded window around the first hit.
                    words = re.findall(r'\w{3,}', request.get('query', ''))
                    hits = [text.lower().find(w.lower()) for w in words]
                    start = max(0, min((h for h in hits if h >= 0), default=0) - 300)
                    excerpt = text[start:start + EXCERPT_CHARS]
                    packet = {'excerpt_id': excerpt_id, 'source_id': source_id,
                              'source': {k: manifest[k] for k in ('title', 'author', 'publisher', 'url', 'resolved_url', 'sha256', 'retrieved_at')},
                              'locator': locator, 'text': excerpt,
                              'text_truncated': chunk['truncated'] or len(excerpt) < len(text),
                              'text_start': start, 'image_number': None, 'verified_examples': []}
                    if manifest['format'] == 'pdf' and len(images) < MAX_IMAGES:
                        images.append(str(self.root / 'objects' / manifest['sha256'] / f'page-{index + 1}.png'))
                        packet['image_number'] = len(images)
                    packet['verified_examples'] = self.examples(source_id, manifest['sha256'], locator)
                    packets.append(packet)
            except MaterialError as exc:
                failures.append({'source_id': source_id, 'reason': str(exc)[:300]})
        return {'materials': packets, 'material_failures': failures, 'images': images}

    def examples(self, source_id, content_hash, locator):
        result = []
        for path in sorted((self.root / 'examples').glob('EX-*.json')):
            value = json.loads(path.read_text())
            if (value.get('source_id'), value.get('source_sha256'), value.get('locator')) == (source_id, content_hash, locator):
                if value.get('id') != 'EX-' + sha(encoded({k: v for k, v in value.items() if k != 'id'}))[:24]:
                    raise MaterialError('A cached example failed its integrity check.')
                result.append(value)
        return result[:2]

    def import_example(self, source_id, locator, notation, review):
        """Explicit local review/import, never called by the recommendation model.

        A review records who compared which source bytes and which musical aspects.
        It is provenance, not an automated claim that OCR or a model is infallible.
        """
        from abc_score import parse_score
        parsed = parse_score(notation)
        manifest = self.fetch(source_id)
        document = self.extract(manifest)
        if locator not in [c['locator'] for c in document['chunks']]:
            raise MaterialError('The example locator is not present in this source.')
        required = {'pitches', 'durations', 'spelling', 'voices', 'expression'}
        if (not isinstance(review, dict) or review.get('source_sha256') != manifest['sha256'] or
                review.get('method') not in ('visual_source_comparison', 'symbolic_source_comparison') or
                set(review.get('checked', [])) != required or not str(review.get('reviewer', '')).strip() or
                not str(review.get('notes', '')).strip() or not str(review.get('scope', '')).strip()):
            raise MaterialError('A source-specific comparison record is required before exact reuse.')
        value = {'source_id': source_id, 'source_sha256': manifest['sha256'], 'locator': locator,
                 'notation': copy.deepcopy(notation), 'notation_sha256': parsed['sha256'],
                 'bars': len(parsed['bars']), 'key': parsed['key'], 'review': copy.deepcopy(review)}
        value['id'] = 'EX-' + sha(encoded(value))[:24]
        atomic(self.root / 'examples' / (value['id'] + '.json'), encoded(value))
        return value

