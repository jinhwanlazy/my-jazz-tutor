// Compare the Python compiler against abcjs's independent audio sequencer.
// No account, network or personal records. Uses the pinned local browser bundle.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const values=JSON.parse(execFileSync('uv',['run','python','-c',`
import json,sys
sys.path.insert(0,'tests')
from test_abc_score import notation
from abc_score import parse_score,playback_for
cases=[notation('F2 A2 B2 c2 |','D,8 |'),
 notation('!mf!(3DEF G2 A2 B2 |','D,8 |'),
 notation('D6 F2- | F2 A2 B4 |','D,8 | G,,8 |'),
 notation('D3/2E/2 F/2G/2 A B c3 |','D,8 |'),
 notation('^G6 G2- | G2 =G2 G4 |','D,8 | G,,8 |'),
 notation('(F2 G2 A2) |','D,6 |','3/4')]
flat=notation('"Bbmaj7"[Bdf]4 (3cde z2 |','B,,8 |')
flat['abc']=flat['abc'].replace('K:D','K:Bb')
cases.append(flat)
voices=notation('F4 E4- | E4 F4 |','D,8 | G,,8 |')
voices['abc']=voices['abc'].replace('{ RH LH }','{ (RH RH2) (LH LH2) }').replace('V:LH clef=bass','V:RH2 clef=treble\\nV:LH clef=bass\\nV:LH2 clef=bass')
voices['abc']+='[V:RH2] z4 A4 | B8 |\\n[V:LH2] A,,4 z4 | B,,8 |\\n'
cases.append(voices)
for c in cases:parse_score(c)
print(json.dumps([{'notation':c,'events':playback_for(c)['events']} for c in cases]))
`],{encoding:'utf8'}));
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/usr/bin/google-chrome',args:['--no-sandbox']});
try {
  const page=await browser.newPage(); await page.setContent('<div id="score"></div>');
  await page.addScriptTag({path:'abcjs.min.js'});
  const outputs=await page.evaluate(values=>values.map(value=>{
    const tune=ABCJS.renderAbc('score',value.notation.abc)[0];
    const audio=tune.setUpAudio({chordsOff:true});
    return {tracks:audio.tracks,svgCount:document.querySelectorAll('#score svg').length};
  }),values);
  const normalize=events=>events.map(e=>({pitch:e.pitch,start:Math.round(e.start*1e6)/1e6,duration:Math.round(e.duration*1e6)/1e6}))
    .sort((a,b)=>a.start-b.start||a.pitch-b.pitch||a.duration-b.duration);
  for (let i=0;i<values.length;i++) {
    const actual=outputs[i].tracks.flat().filter(e=>e.cmd==='note')
      .map(e=>({pitch:e.pitch,start:e.start*4,duration:e.duration*4}));
    assert.equal(outputs[i].svgCount,1);
    const expected=normalize(values[i].events),heard=normalize(actual);
    assert.equal(heard.length,expected.length,`case ${i}: note count`);
    for(let n=0;n<expected.length;n++) {
      assert.equal(heard[n].pitch,expected[n].pitch,`case ${i} note ${n}: pitch`);
      assert.ok(Math.abs(heard[n].start-expected[n].start)<.00001,`case ${i} note ${n}: onset`);
      assert.ok(Math.abs(heard[n].duration-expected[n].duration)<.00001,`case ${i} note ${n}: duration`);
    }
  }
  await mkdir('build/abc-interop',{recursive:true});
  await writeFile('build/abc-interop/result.json',JSON.stringify({cases:values.length,outputs},null,2));
  console.log(`ABC server/browser pitch and duration agreement: ${values.length} cases passed.`);
} finally {await browser.close();}
