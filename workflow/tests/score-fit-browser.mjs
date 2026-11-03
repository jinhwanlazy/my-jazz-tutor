// Full-score visibility in the actual app; synthetic exercises, no Codex or private data.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const project=resolve(import.meta.dirname,'..'),root=await mkdtemp(join(tmpdir(),'jazz-browser-score-fit-'));
const output=join(project,'build/score-layout-0.10.0');await mkdir(output,{recursive:true});
await writeFile(join(root,'profile.json'),'{"daily_minutes":30,"language":"en"}');
const server=spawn('uv',['run','python','tests/serve_browser.py',root],{cwd:project});let browser;
try {
  const url=await new Promise((resolve,reject)=>{
    let log='';const timer=setTimeout(()=>reject(Error(log||'Server timeout')),15000);
    server.stdout.on('data',chunk=>{log+=chunk;const match=log.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});
    server.stderr.on('data',chunk=>log+=chunk);server.on('error',reject);
  });
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/usr/bin/google-chrome',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],results=[],requests=[];
  page.on('request',request=>{if(request.method()==='POST')requests.push({url:new URL(request.url()).pathname,body:request.postDataJSON()});});
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  const state=()=>page.evaluate(()=>fetch('/api/state?lang=en').then(r=>r.json()));
  await page.goto(url);await page.waitForFunction(()=>document.querySelector('#connection').textContent==='Connected locally');
  for(const bars of [4,8,12,16]){
    await page.locator('#view-list').waitFor({state:'visible'});
    await page.waitForFunction(()=>!document.querySelector('#new-practice').disabled);
    await page.locator('#recommendation-focus').evaluate(e=>e.open=true);
    await page.locator('#recommendation-request').fill('simulate:abc'+bars);await page.locator('#new-practice').click();
    await page.waitForFunction(n=>document.querySelectorAll('.practice-item').length===n,bars/4);
    await page.waitForFunction(()=>!document.querySelector('#new-practice').disabled);
    const before=(await state()).history[0];assert.equal(before.target.bars,bars);
    const snapshot=JSON.stringify(before.target);
    await page.locator('.history-item').first().click();
    for(const [width,height] of [[1440,1000],[1280,720],[1024,600],[768,1024],[390,844],[320,640],[844,390],[640,360]]){
      await page.setViewportSize({width,height});await page.locator('#go-score').click();
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      const value=await page.evaluate(()=>{
        const root=document.querySelector('#score-viewport'),svg=root.querySelector('svg'),r=svg.getBoundingClientRect();
        const toolbar=document.querySelector('#practice-toolbar').getBoundingClientRect(),box=svg.viewBox.baseVal;
        const notes=[...svg.querySelectorAll('.abcjs-notehead')].map(node=>node.getBoundingClientRect());
        return {top:r.top,bottom:r.bottom,width:r.width,height:r.height,toolbarBottom:toolbar.bottom,
          viewportHeight:visualViewport.height,pageOverflow:document.documentElement.scrollWidth-innerWidth,
          scoreOverflow:root.scrollWidth-root.clientWidth,aspectError:Math.abs(r.width/box.width-r.height/box.height),
          staves:svg.querySelectorAll('.abcjs-clef').length,
          notesContained:notes.length>0&&notes.every(n=>n.left>=r.left-1&&n.right<=r.right+1&&n.top>=r.top-1&&n.bottom<=r.bottom+1)};
      });
      results.push({bars,viewport:{width,height},...value});
      assert.ok(value.width>0&&value.height>30,JSON.stringify(results.at(-1)));
      assert.ok(value.top>=value.toolbarBottom-1&&value.bottom<=value.viewportHeight-10,JSON.stringify(results.at(-1)));
      assert.ok(value.pageOverflow<=1&&value.scoreOverflow<=1&&value.aspectError<.001&&value.notesContained,JSON.stringify(results.at(-1)));
      assert.equal(value.staves,Math.ceil(bars/4)*2);
      if([1280,390].includes(width))await page.screenshot({path:join(output,`score-${bars}-${width}.png`)});
    }
    assert.equal(JSON.stringify((await state()).history.find(t=>t.id===before.id).target),snapshot);
    if(bars<16)await page.locator('#back-list').click();
  }
  // An entire sweep crosses all four systems without moving the page or creating input.
  await page.setViewportSize({width:1280,height:720});await page.locator('#tempo').fill('240');await page.locator('#tempo').dispatchEvent('change');
  await page.locator('#reference-play').click();await page.locator('#replay-actions').waitFor({state:'visible'});
  const scroll=await page.evaluate(()=>scrollY);
  await page.waitForFunction(()=>document.querySelector('#score-position').textContent.includes('Bar 9'),{},{timeout:12000});
  assert.ok(Math.abs(await page.evaluate(()=>scrollY)-scroll)<2,'playback scrolled at a line boundary');
  await page.locator('#replay-actions').waitFor({state:'hidden',timeout:12000});
  assert.ok(Math.abs(await page.evaluate(()=>scrollY)-scroll)<2,'playback completion scrolled');
  assert.equal((await state()).sessions.length,0);
  const practiceScroll=await page.evaluate(()=>scrollY);
  await page.locator('.nav-button[data-view="settings"]').click();assert.equal(await page.evaluate(()=>scrollY),0);
  await page.locator('#language-select').selectOption('ko');
  assert.equal(await page.locator('#view-settings [data-learn-action]').count(),3);
  assert.equal(await page.locator('#assessment-mode').inputValue(),'automatic');
  await page.screenshot({path:join(output,'settings-ko.png'),fullPage:true});
  await page.locator('#settings-back').click();assert.ok(Math.abs(await page.evaluate(()=>scrollY)-practiceScroll)<2);
  await page.locator('#playback-settings').evaluate(e=>e.open=true);
  assert.equal(await page.locator('#playback-settings [data-learn-action],#score-follow,#keyboard-shortcuts,#tempo-range,#manual-mode').count(),0);
  assert.match(await page.locator('#practice-btn').getAttribute('title'),/R.*패드 7/);
  assert.equal(await page.locator('#error').isVisible(),false);assert.deepEqual(errors,[]);
  await writeFile(join(output,'fit-results.json'),JSON.stringify({passed:true,results,errors,requests},null,2));
  console.log('Full score fit: 32 viewport/bar combinations, stationary playback, settings and Korean tooltips passed.');
} catch(error){const page=browser?.contexts()[0]?.pages()[0];if(page){await page.screenshot({path:join(output,'fit-failure.png'),fullPage:true});await writeFile(join(output,'fit-failure.txt'),await page.locator('body').innerText());}throw error;
} finally {await browser?.close();server.kill('SIGTERM');await rm(root,{recursive:true,force:true});}
