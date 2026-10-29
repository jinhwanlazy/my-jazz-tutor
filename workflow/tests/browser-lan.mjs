// Optional real HTTP LAN-origin check. Uses temporary data and a synthetic provider.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const address = process.env.JAZZ_TEST_LAN_HOST;
if (!address || !/^\d+\.\d+\.\d+\.\d+$/.test(address) || address.startsWith('127.') || address === '0.0.0.0') {
  throw new Error('Set JAZZ_TEST_LAN_HOST to this computer’s actual LAN IPv4 address.');
}
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const project = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = await mkdtemp(join(tmpdir(), 'jazz-browser-lan-'));
await writeFile(join(root, 'profile.json'), '{"daily_minutes":20,"goal":"Synthetic LAN integration test"}');
const server = spawn('uv', ['run','python','tests/serve_browser.py',root,'0.0.0.0'], {cwd:project});
let browser;
try {
  const port = await new Promise((resolve,reject) => {
    let output=''; const timer=setTimeout(()=>reject(new Error('Server startup timed out')),10000);
    server.stdout.on('data',chunk=>{output+=chunk;const m=output.match(/http:\/\/127\.0\.0\.1:(\d+)/);if(m){clearTimeout(timer);resolve(m[1]);}});
    server.stderr.on('data',chunk=>process.stderr.write(chunk));
    server.on('error',error=>{clearTimeout(timer);reject(error);});
    server.on('exit',code=>{clearTimeout(timer);reject(new Error(`Server exited ${code}`));});
  });
  browser = await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{}),args:['--no-sandbox','--no-proxy-server']});
  const page=await browser.newPage(), errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const state=()=>page.evaluate(()=>fetch('/api/state').then(response=>response.json()));
  await page.goto(`http://${address}:${port}`);
  await page.waitForFunction(()=>document.querySelector('#connection').textContent==='Connected locally');
  assert.deepEqual(await page.evaluate(()=>({secure:isSecureContext,uuid:typeof crypto.randomUUID,random:typeof crypto.getRandomValues})),
    {secure:false,uuid:'undefined',random:'function'});
  await page.locator('#new-practice').click();
  await page.waitForFunction(()=>document.querySelector('#generation-title').textContent==='Your new practice is in the list.');
  assert.equal(await page.locator('#view-practice').isVisible(),false);
  await page.locator('.history-item').first().click();
  await page.locator('#view-practice').waitFor({state:'visible'});
  await page.locator('#playback-settings > summary').click();
  await page.locator('#midi-connect').click();
  assert.match(await page.locator('#midi-status').textContent(),/HTTPS or localhost/);
  await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>document.querySelector('#practice-btn').textContent==='Pause');
  await page.waitForTimeout(700);
  await page.locator('#finish-btn').click();
  await page.locator('#view-list').waitFor({state:'visible'});
  let data=await state();
  assert.equal(data.history.length,1);assert.equal(data.history[0].completed,true);
  assert.equal(data.sessions.length,1);assert.equal(data.sessions[0].status,'finished');
  assert.match(data.sessions[0].id,/^S-[0-9a-f]{32}$/);
  await page.locator('[data-rating="good"]').click();
  await page.waitForFunction(()=>document.querySelector('[data-rating="good"]').getAttribute('aria-pressed')==='true');
  await page.locator('#close-record').click();
  await page.locator('.history-item').first().click();
  await page.locator('#history-dialog').waitFor({state:'visible'});
  await page.locator('#repeat-btn').click();
  await page.locator('#history-dialog').waitFor({state:'hidden'});
  data=await state();
  assert.equal(data.history.length,2);assert.equal(data.history.filter(t=>t.pending).length,1);
  assert.equal(data.status.reported_attempts,1);assert.equal(await page.locator('#view-practice').isVisible(),false);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,origin:`http://${address}:${port}`,secure_context:false,
    checks:['generation without randomUUID','metronome and recording save over HTTP','completion and feedback','repeat task IDs','explicit MIDI limitation']}));
} finally {
  if(browser)await browser.close();
  if(server.pid && server.exitCode === null && server.signalCode === null) {
    const exited=once(server,'exit');server.kill('SIGTERM');await exited;
  }
  await rm(root,{recursive:true,force:true});
}
