"""Local score extraction workbench. Candidates never enter recommendations.

PDF/video -> image -> optional external Audiveris -> MusicXML -> ABC -> explicit
source comparison -> reviewed example. All source bytes/artifacts stay in cache.
Run --help for the development CLI; no practice records are read or written.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

from materials import MaterialStore, MaterialError, atomic, encoded, sha, HERE
from musicxml_import import convert

VERSION = 'score-extract-1'


def checked_crop(crop):
    if (not isinstance(crop, list) or len(crop) != 4 or
            any(type(n) not in (int, float) or not math.isfinite(n) for n in crop)):
        raise MaterialError('Crop must be normalized [x, y, width, height].')
    x, y, w, h = crop
    if not (0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0 and x + w <= 1.000001 and y + h <= 1.000001):
        raise MaterialError('Crop is outside the source image.')
    return crop


def run(command, cwd, *, timeout=120, env=None):
    """Kill the whole tool process group on timeout, retaining a bounded log."""
    log = Path(cwd) / 'tool.log'
    with log.open('wb') as stream:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            raise MaterialError('Extraction tool is unavailable: ' + str(command[0])) from exc
        try:
            status = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); process.wait()
            raise MaterialError('Extraction tool timed out; candidate remains unreviewed.') from None
    if log.stat().st_size > 2_000_000:
        with log.open('rb') as stream: tail = stream.read(2_000_000)
        log.write_bytes(tail)
    if status:
        raise MaterialError(f'Extraction tool exited with code {status}; inspect tool.log.')


def raster(source, output, selection):
    """Worker only: keep PDFium out of the multi-threaded web process."""
    from PIL import Image, ImageOps
    crop = checked_crop(selection['crop'])
    if selection['kind'] == 'pdf':
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(source) as document:
            number = selection['page']
            if type(number) is not int or not 1 <= number <= min(300, len(document)):
                raise MaterialError('PDF page does not exist.')
            page = document[number - 1]
            width, height = page.get_size()
            bitmap = page.render(scale=min(4, 4000 / max(width, height)))
            image = bitmap.to_pil().copy()
            bitmap.close(); page.close()
    else:
        with Image.open(source) as frame: image = frame.convert('RGB')
    try:
        width, height = image.size
        x, y, w, h = crop
        box = tuple(round(n) for n in (x * width, y * height, (x + w) * width, (y + h) * height))
        if box[2] - box[0] < 50 or box[3] - box[1] < 50:
            raise MaterialError('Score crop is too small for inspection.')
        cropped = image.crop(box)
        ImageOps.expand(cropped, border=40, fill='white').convert('RGB').save(output)
        return {'source_dimensions': [width, height], 'crop_pixels': list(box), 'border_pixels': 40}
    finally:
        image.close()


def candidate(store, spec):
    source_id = spec['source_id']
    manifest = store.fetch(source_id)
    locator = spec['locator']
    document = store.extract(manifest)
    if locator not in [c['locator'] for c in document['chunks']]:
        raise MaterialError('Select a locator from material-source output.')
    selection = copy.deepcopy(spec.get('selection', {}))
    kind = selection.get('kind')
    if kind not in ('pdf', 'musicxml', 'video') or manifest['format'] not in {'pdf': ['pdf'], 'musicxml': ['musicxml', 'mxl'], 'video': ['video']}[kind]:
        raise MaterialError('Extraction selection does not match source format.')
    if kind != 'musicxml': checked_crop(selection.get('crop'))
    if kind == 'pdf' and selection.get('page') != locator.get('page'):
        raise MaterialError('Crop page and source locator disagree.')
    if kind == 'video':
        seconds = selection.get('seconds')
        if type(seconds) not in (float, int) or not math.isfinite(seconds) or not 0 <= seconds <= 14400:
            raise MaterialError('Select one video timestamp from 0–14400 seconds.')
    source = store.root / 'objects' / manifest['sha256'] / 'original'
    store.root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='candidate-', dir=store.root) as name:
        work = Path(name).resolve()
        result = {'version': VERSION, 'state': 'unreviewed', 'source_id': source_id, 'source_sha256': manifest['sha256'],
                  'source': manifest, 'locator': locator, 'selection': selection, 'issues': [], 'conversion': None,
                  'notation': None, 'files': {}, 'tool': None, 'raster': None}
        raw = None
        try:
            if kind == 'musicxml':
                raw = source.read_bytes()
            else:
                raster_source = source.resolve()
                if kind == 'video':
                    ffmpeg = os.environ.get('JAZZ_FFMPEG_BIN') or shutil.which('ffmpeg')
                    if not ffmpeg: raise MaterialError('ffmpeg is required for selected video frames.')
                    frame = work / 'frame.png'
                    run([ffmpeg, '-nostdin', '-v', 'error', '-ss', str(selection['seconds']), '-i', str(raster_source),
                         '-frames:v', '1', '-vf', 'scale=2400:2400:force_original_aspect_ratio=decrease', str(frame)], work, timeout=30)
                    raster_source = frame
                image = work / 'source.png'
                run([sys.executable, str(HERE / 'score_extract.py'), '_raster', str(raster_source), str(image), json.dumps(selection)], work, timeout=30)
                result['raster'] = json.loads((work / 'tool.log').read_text())
                tool = os.environ.get('JAZZ_AUDIVERIS_BIN') or shutil.which('Audiveris') or shutil.which('audiveris')
                if not tool: raise MaterialError('Audiveris is optional and is not installed; inspect the source image or configure JAZZ_AUDIVERIS_BIN.')
                tool = str(Path(tool).resolve())
                run([tool, '-version'], work, timeout=20)
                version_log = (work / 'tool.log').read_text(errors='replace')[-2000:]
                result['tool'] = {'name': 'Audiveris', 'version_output': version_log, 'launcher_sha256': sha(Path(tool).read_bytes())}
                env = dict(os.environ, XDG_CACHE_HOME=str(work / 'tool-cache'), XDG_CONFIG_HOME=str(work / 'tool-config'))
                run([tool, '-batch', '-export', '-output', str(work / 'omr'), '--', str(image)], work, env=env)
                exports = list((work / 'omr').rglob('*.mxl')) + list((work / 'omr').rglob('*.musicxml'))
                if len(exports) != 1: raise MaterialError('OMR must export exactly one piano score; select a smaller crop.')
                if exports[0].stat().st_size > 8_000_000: raise MaterialError('OMR result exceeds 8 MB.')
                raw = exports[0].read_bytes()
            atomic(work / 'raw-score', raw)
            conversion = convert(raw, **{k: selection[k] for k in ('first', 'last', 'missing_key', 'missing_meter') if k in selection})
            result['conversion'] = {k: v for k, v in conversion.items() if k != 'notation'}
            result['notation'] = conversion['notation']
        except (ValueError, OSError, KeyError, ZeroDivisionError) as exc:
            result['issues'].append(str(exc)[:1000])
        for filename in ('source.png', 'raw-score', 'tool.log'):
            path = work / filename
            if path.exists(): result['files'][filename] = sha(path.read_bytes())
        result['id'] = 'CAND-' + sha(encoded(result))[:24]
        directory = store.root / 'candidates' / result['id']
        for filename in result['files']: atomic(directory / filename, (work / filename).read_bytes())
        atomic(directory / 'candidate.json', encoded(result))
        return result


def read_candidate(store, identity):
    if not re.fullmatch(r'CAND-[a-f0-9]{24}', identity): raise MaterialError('Invalid candidate ID.')
    directory = store.root / 'candidates' / identity
    result = json.loads((directory / 'candidate.json').read_text())
    if result.get('id') != identity or identity != 'CAND-' + sha(encoded({k: v for k, v in result.items() if k != 'id'}))[:24]:
        raise MaterialError('Candidate integrity check failed.')
    for filename, digest in result['files'].items():
        if filename not in ('source.png', 'raw-score', 'tool.log') or sha((directory / filename).read_bytes()) != digest:
            raise MaterialError('Candidate artifact integrity check failed.')
    return result


def register(store, identity, review, *, notation=None, learning=None):
    value = read_candidate(store, identity)
    if not {'source.png', 'raw-score'}.intersection(value['files']):
        raise MaterialError('No extracted score/image exists to compare.')
    chosen = notation or value['notation']
    if chosen is None: raise MaterialError('Supply corrected ABC after inspecting the failed extraction.')
    if value['selection']['kind'] in ('pdf', 'video') and review.get('method') != 'visual_source_comparison':
        raise MaterialError('Image/OMR candidates require visual comparison with the source, not just the intermediate XML.')
    corrections = review.get('corrections', [])
    if (value['issues'] or chosen != value['notation']) and (not isinstance(corrections, list) or not corrections or not all(isinstance(s, str) and s.strip() for s in corrections)):
        raise MaterialError('Record the source comparison corrections; failed/changed extraction cannot be silently promoted.')
    review = copy.deepcopy(review)
    if review.get('candidate_id') != identity or review.get('source_sha256') != value['source_sha256']:
        raise MaterialError('Review must identify the exact candidate and source bytes.')
    review['extraction'] = {k: value[k] for k in ('id', 'version', 'selection', 'files', 'tool', 'conversion', 'issues')}
    return store.import_example(value['source_id'], value['locator'], chosen, review, learning=learning)


def comparison(store, identity, output, *, notation=None):
    """Standalone source/candidate comparison; no source copied into tracked files."""
    value = read_candidate(store, identity)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    directory = store.root / 'candidates' / identity
    if 'source.png' in value['files']: shutil.copyfile(directory / 'source.png', output / 'source.png')
    shutil.copyfile(HERE / 'abcjs.min.js', output / 'abcjs.js')
    payload = json.dumps({'candidate': value, 'corrected': notation}, ensure_ascii=False).replace('<', '\\u003c')
    source_view = '<img src="source.png" alt="Selected source score">' if 'source.png' in value['files'] else '<p>Symbolic source; inspect the cached raw-score and its MusicXML timeline.</p>'
    markup = '''<!doctype html><meta charset="utf-8"><title>악보 추출 비교</title>
<style>body{font:16px system-ui;background:#f3f1eb;color:#252720;margin:0;padding:24px}h1{font-size:24px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}article{background:white;padding:20px;border-radius:12px;min-width:0}img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}#score{overflow:auto}button{padding:10px;margin-right:8px;cursor:pointer}.notice{background:#fff0c8;padding:12px}a{color:#16543d}@media(max-width:800px){.grid{grid-template-columns:1fr}}</style>
<h1>원본과 추출 악보 비교</h1><p class="notice">검토용 후보입니다. 음표·리듬·성부·표현을 원본과 비교하기 전에는 추천 예제로 사용할 수 없습니다.</p>
<p id="source"></p><div class="grid"><article><h2>출처 원본</h2>''' + source_view + '''<pre id="selection"></pre></article>
<article><h2>ABC 변환 결과</h2><button id="raw">최초 추출</button><button id="fixed">수정본</button><div id="score"></div><pre id="issues"></pre><details><summary>ABC 원문</summary><pre id="abc"></pre></details></article></div>
<script src="abcjs.js"></script><script>const data=PAYLOAD;const c=data.candidate;
const link=document.createElement('a');link.href=c.source.url;link.textContent=c.source.author+' · '+c.source.title+' · '+c.locator.label;document.querySelector('#source').append(link);
document.querySelector('#selection').textContent=JSON.stringify(c.selection,null,2);
function show(corrected){const n=corrected?data.corrected:c.notation;document.querySelector('#score').replaceChildren();document.querySelector('#abc').textContent=n?.abc||'';document.querySelector('#issues').textContent=corrected?'수정본도 별도 출처 검토 기록이 필요합니다.':c.issues.join('\\n')||'구조 검증 통과. 원본 충실도는 아직 미검토입니다.';if(n)ABCJS.renderAbc('score',n.abc,{responsive:'resize',add_classes:true});}
document.querySelector('#raw').onclick=()=>show(false);document.querySelector('#fixed').disabled=!data.corrected;document.querySelector('#fixed').onclick=()=>show(true);show(!!data.corrected);</script>'''.replace('PAYLOAD', payload)
    (output / 'index.html').write_text(markup)
    return str(output / 'index.html')


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '_raster':
        print(json.dumps(raster(sys.argv[2], sys.argv[3], json.loads(sys.argv[4])))); return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True, help='Explicit local development cache; no practice directory')
    parser.add_argument('--catalog', type=Path, help='Optional local source catalog for a pilot')
    commands = parser.add_subparsers(dest='command', required=True)
    extract = commands.add_parser('extract'); extract.add_argument('--input', type=Path, required=True)
    render = commands.add_parser('compare'); render.add_argument('candidate_id'); render.add_argument('--output', type=Path, required=True); render.add_argument('--notation', type=Path)
    reviewed = commands.add_parser('register'); reviewed.add_argument('candidate_id'); reviewed.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    if (args.cache / 'practice.csv').exists() or (args.cache / 'profile.json').exists(): raise MaterialError('Use a materials cache, not a practice directory.')
    store = MaterialStore(args.cache, json.loads(args.catalog.read_text())['sources'] if args.catalog else None)
    if args.command == 'extract': result = candidate(store, json.loads(args.input.read_text()))
    elif args.command == 'compare': result = comparison(store, args.candidate_id, args.output, notation=json.loads(args.notation.read_text()) if args.notation else None)
    else:
        value = json.loads(args.input.read_text())
        result = register(store, args.candidate_id, value['review'], notation=value.get('notation'), learning=value.get('learning'))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
