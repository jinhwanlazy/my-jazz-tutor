import test from 'node:test';
import assert from 'node:assert/strict';
import {Capture, encodeMidi, base64, uploadPending} from '../capture.mjs';

class MemoryOutbox {
  constructor() { this.saved = []; this.draft = null; }
  async putPacket(id, packet) { if (this.failWrite) { this.failWrite = false; throw new Error('disk full'); } this.saved.push({key:`${id}:${packet.sequence}`, id, packet}); }
  async packets(id) { return this.saved.filter(p => p.id === id).sort((a,b) => a.packet.sequence-b.packet.sequence); }
  async removePacket(key) { this.saved = this.saved.filter(p => p.key !== key); }
  async putDraft(draft) { this.draft = draft; }
  async removeDraft() { this.draft = null; }
}

test('binary MIDI frame preserves fractional timestamps, input index, and raw bytes', () => {
  const encoded = encodeMidi([{at_ms:1234.125, port:12, data:Uint8Array.of(0x91,64,127)}, {at_ms:1500,port:3,data:Uint8Array.of(0xf8)}]);
  const view = new DataView(encoded.buffer);
  assert.equal(view.getFloat64(0,true),1234.125);
  assert.equal(view.getUint16(8,true),12);
  assert.equal(view.getUint16(10,true),3);
  assert.deepEqual([...encoded.subarray(12,15)],[0x91,64,127]);
  assert.equal(view.getFloat64(15,true),1500);
  assert.deepEqual(Buffer.from(base64(encoded),'base64'),Buffer.from(encoded));
  assert.throws(() => encodeMidi([{at_ms:NaN,port:0,data:[1]}]));
});

test('failed local save retains MIDI, and stop retries freeze performance time before storage delays', async () => {
  const original = globalThis.performance;
  let now=1000;
  Object.defineProperty(globalThis,'performance',{configurable:true,value:{now:()=>now}});
  try {
    const outbox=new MemoryOutbox(), received=[];
    const capture=new Capture({id:'S-test',task_id:'T-test'},outbox,async (path,body) => {
      if(path.endsWith('chunk')) received.push(body.packet);
      return {status:'finished'};
    });
    now=2000; capture.event('play',{bpm:60});
    capture.midi([0x90,60,100],0,2000);
    now=3000; capture.midi([0x80,60,0],0,3000); capture.event('pause');
    outbox.failWrite=true;
    await assert.rejects(capture.stop(),/disk full/);
    assert.equal(capture.frames.length,2);
    now=15000;
    assert.equal((await capture.stop()).status,'finished');
    assert.equal(received.length,1);
    assert.equal(received[0].elapsed_ms,2000);
    assert.equal(received[0].events.length,2);
    assert.equal(Buffer.from(received[0].midi,'base64').length,30);
    assert.equal(outbox.saved.length,0);
    assert.equal(outbox.draft,null);
  } finally {Object.defineProperty(globalThis,'performance',{configurable:true,value:original});}
});

test('lost response leaves the exact packet queued for idempotent retry', async () => {
  const outbox=new MemoryOutbox(), requests=[];
  const packet={sequence:0,events:[],midi:'',elapsed_ms:1234};
  await outbox.putPacket('S-test',packet);
  await assert.rejects(uploadPending(outbox,'S-test',async (_path,body)=>{requests.push(body.packet);throw new Error('offline');}));
  assert.equal(outbox.saved.length,1);
  await uploadPending(outbox,'S-test',async (_path,body)=>requests.push(body.packet));
  assert.deepEqual(requests,[packet,packet]);
  assert.equal(outbox.saved.length,0);
});

test('finish retry does not duplicate a sealed capture', async () => {
  const outbox=new MemoryOutbox();let failFinish=true, packets=0;
  const capture=new Capture({id:'S-test',task_id:'T-test'},outbox,async path=>{
    if(path.endsWith('chunk')) packets++;
    if(path.endsWith('finish') && failFinish) {failFinish=false;throw new Error('lost finish response');}
    return {status:'finished'};
  });
  await assert.rejects(capture.stop());
  assert.equal(outbox.draft.finished,true);
  assert.equal((await capture.stop()).status,'finished');
  assert.equal(packets,1);
});
