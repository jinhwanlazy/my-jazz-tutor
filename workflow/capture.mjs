// getRandomValues also works on plain HTTP LAN origins, where randomUUID is absent.
export function randomHex(bytes = 16) {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), byte => byte.toString(16).padStart(2, '0')).join('');
}

// JPM1 export: magic, then repeated little-endian f64 milliseconds/u16 port/u16 length/bytes.
export function encodeMidi(messages) {
  const bytes = new Uint8Array(messages.reduce((n, m) => n + 12 + m.data.length, 0));
  const view = new DataView(bytes.buffer);
  let offset = 0;
  for (const m of messages) {
    if (!Number.isFinite(m.at_ms) || m.at_ms < 0 || !Number.isInteger(m.port) || m.port < 0 || m.port > 65535 || !m.data.length || m.data.length > 65535) {
      throw new Error('Invalid MIDI frame values.');
    }
    view.setFloat64(offset, m.at_ms, true);
    view.setUint16(offset + 8, m.port, true);
    view.setUint16(offset + 10, m.data.length, true);
    bytes.set(m.data, offset + 12);
    offset += 12 + m.data.length;
  }
  return bytes;
}

export function base64(bytes) {
  let text = '';
  for (let i = 0; i < bytes.length; i += 8192) text += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(text);
}

export class Outbox {
  constructor(workspace) { this.workspace = workspace; }
  async database() {
    if (!this.db) this.db = await new Promise((resolve, reject) => {
      const request = indexedDB.open(`jazz-recordings-${this.workspace}`, 1);
      request.onupgradeneeded = () => {
        request.result.createObjectStore('packets', {keyPath: 'key'});
        request.result.createObjectStore('drafts', {keyPath: 'id'});
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(new Error('Could not open browser storage. Check available storage space.'));
      request.onblocked = () => reject(new Error('Close other practice tabs and try again.'));
    });
    return this.db;
  }
  async operation(store, mode, fn) {
    const db = await this.database();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, mode);
      const request = fn(tx.objectStore(store));
      tx.oncomplete = () => resolve(request?.result);
      tx.onerror = () => reject(tx.error || new Error('Could not save to browser storage.'));
      tx.onabort = () => reject(tx.error || new Error('Saving to browser storage was interrupted.'));
    });
  }
  putDraft(draft) { return this.operation('drafts', 'readwrite', s => s.put(draft)); }
  drafts() { return this.operation('drafts', 'readonly', s => s.getAll()); }
  removeDraft(id) { return this.operation('drafts', 'readwrite', s => s.delete(id)); }
  putPacket(id, packet) { return this.operation('packets', 'readwrite', s => s.put({key: `${id}:${String(packet.sequence).padStart(8, '0')}`, id, packet})); }
  removePacket(key) { return this.operation('packets', 'readwrite', s => s.delete(key)); }
  async packets(id) { return (await this.operation('packets', 'readonly', s => s.getAll())).filter(p => p.id === id).sort((a, b) => a.packet.sequence - b.packet.sequence); }
}

export async function uploadPending(outbox, id, api) {
  for (const queued of await outbox.packets(id)) {
    await api('/api/sessions/chunk', {session_id: id, packet: queued.packet});
    await outbox.removePacket(queued.key);
  }
}

export class Capture {
  constructor(session, outbox, api, onStatus = () => {}) {
    Object.assign(this, {session, outbox, api, onStatus});
    this.origin = performance.now();
    this.frames = [];
    this.events = [];
    this.sequence = 0;
    this.localChain = Promise.resolve();
    this.uploadChain = Promise.resolve();
    this.noteCount = 0;
    this.ended = false;
    this.sealed = false;
  }
  async begin() {
    await this.outbox.putDraft({id: this.session.id, task_id: this.session.task_id, finished: false});
    this.interval = setInterval(() => this.autosave(), 3000);
  }
  autosave() {
    if (this.ended || this.saving) return;
    this.saving = this.checkpoint().then(() => this.upload())
      .catch(error => this.onStatus(error.message, true)).finally(() => { this.saving = null; });
  }
  event(type, values = {}, at = performance.now()) {
    if (!this.ended) this.events.push({...values, type, at_ms: Math.max(0, at - this.origin)});
  }
  midi(data, port, at) {
    if (this.ended) return;
    this.frames.push({at_ms: Math.max(0, Math.min(at, performance.now()) - this.origin), port, data: Uint8Array.from(data)});
    if ((data[0] & 0xf0) === 0x90 && data[2] > 0) this.noteCount++;
    // Bound a busy controller's in-memory buffer even between regular checkpoints.
    if (this.frames.length >= 12000) this.autosave();
  }
  checkpoint() {
    const save = async () => {
      const frames = this.frames.splice(0), events = this.events.splice(0);
      const elapsed_ms = [...events, ...frames].reduce((last, item) => Math.max(last, item.at_ms),
        (this.endAt ?? performance.now()) - this.origin);
      const packet = {sequence: this.sequence, midi: base64(encodeMidi(frames)), events, elapsed_ms};
      try {
        await this.outbox.putPacket(this.session.id, packet);
        this.sequence++;
      } catch (error) {
        this.frames = frames.concat(this.frames);
        this.events = events.concat(this.events);
        throw error;
      }
    };
    const next = this.localChain.then(save);
    this.localChain = next.catch(() => {});
    return next;
  }
  upload() {
    const next = this.uploadChain.then(() => uploadPending(this.outbox, this.session.id, this.api));
    this.uploadChain = next.catch(() => {});
    return next.then(() => this.onStatus('Autosaved', false), error => {
      this.onStatus('Saved in browser · will retry when connected', true);
      throw error;
    });
  }
  async stop() {
    if (!this.ended) {
      clearInterval(this.interval);
      this.ended = true;
      this.endAt = performance.now();
    }
    if (!this.sealed) {
      await this.checkpoint();
      await this.outbox.putDraft({id: this.session.id, task_id: this.session.task_id, finished: true, expected_chunks: this.sequence});
      this.sealed = true;
    }
    await this.upload();
    const finished = await this.api('/api/sessions/finish', {session_id: this.session.id, expected_chunks: this.sequence});
    await this.outbox.removeDraft(this.session.id);
    return finished;
  }
}
