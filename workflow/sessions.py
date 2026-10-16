"""Durable web recordings. MIDI observations never grade a practice task."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import struct
import uuid

import review as r

FRAME = struct.Struct("<dHH")  # elapsed milliseconds, input index, byte count
MAX_MS = 24 * 60 * 60 * 1000
EVENTS = {"play", "pause", "tempo", "pad", "click", "device", "disconnect",
          "visibility", "audio_interrupted", "recovered"}


def midi_messages(blob):
    offset = 0
    while offset < len(blob):
        r.require(len(blob) - offset >= FRAME.size, "The MIDI frame is truncated.")
        at, port, size = FRAME.unpack_from(blob, offset)
        offset += FRAME.size
        r.require(math.isfinite(at) and 0 <= at <= MAX_MS, "Invalid MIDI timestamp.")
        r.require(0 < size <= 65535 and offset + size <= len(blob), "The MIDI message is truncated.")
        yield at, port, blob[offset:offset + size]
        offset += size


def measurements(chunks, interrupted=False):
    """Only input boundaries and transport settings; no musical scoring."""
    elapsed = max((c["elapsed_ms"] for c in chunks), default=0)
    events = sorted((e for c in chunks for e in c["events"]), key=lambda e: e["at_ms"])
    midi = sorted((m for c in chunks for m in midi_messages(c["midi"])), key=lambda m: m[0])
    playing_since, active, bpm = None, 0, None
    tempos, gaps = [], []
    for event in events:
        at = min(event["at_ms"], elapsed)
        kind = event["type"]
        if kind in ("play", "tempo"):
            bpm = event["bpm"]
            tempos.append((at, bpm))
        if kind == "play" and playing_since is None:
            playing_since = at
        if kind == "pause" and playing_since is not None:
            active += max(0, at - playing_since)
            playing_since = None
        if kind in ("disconnect", "audio_interrupted", "recovered"):
            gaps.append(kind)
    if playing_since is not None:
        active += max(0, elapsed - playing_since)
    held, sustained, pedals = set(), set(), set()
    first, last, last_on, notes = None, None, None, 0
    for at, port, message in midi:
        if at > elapsed:
            continue
        status = message[0] & 0xF0
        channel = (port, message[0] & 0x0F)
        if status in (0x80, 0x90) and len(message) == 3:
            note = (*channel, message[1])
            if status == 0x90 and message[2] > 0:
                held.add(note)
                sustained.discard(note)
                first = at if first is None else first
                last_on, last, notes = at, at, notes + 1
            elif note in held:
                held.remove(note)
                if channel in pedals:
                    sustained.add(note)
                last = at
        elif status == 0xB0 and len(message) == 3:
            control, value = message[1:]
            if control == 64:
                if value >= 64:
                    pedals.add(channel)
                else:
                    pedals.discard(channel)
                    released = {n for n in sustained if n[:2] == channel}
                    if released:
                        last = at
                        sustained -= released
            elif control == 120:  # All Sound Off also silences sustained notes.
                affected = {n for n in held | sustained if n[:2] == channel}
                if affected:
                    held -= affected
                    sustained -= affected
                    last = at
            elif control == 123:  # All Notes Off still respects the sustain pedal.
                released = {n for n in held if n[:2] == channel}
                if released:
                    held -= released
                    if channel in pedals:
                        sustained |= released
                    last = at
            elif control == 121:  # Reset All Controllers releases sustain, not held keys.
                pedals.discard(channel)
                released = {n for n in sustained if n[:2] == channel}
                if released:
                    sustained -= released
                    last = at
    complete = first is not None and not held and not sustained and not gaps and not interrupted
    span = max(0, last - first) if complete else None
    last_note_bpm = next((value for at, value in reversed(tempos) if at <= last_on), None) if last_on is not None else None
    return {"elapsed_ms": elapsed, "active_ms": active, "midi_messages": len(midi),
            "note_ons": notes, "first_note_ms": first, "last_note_ms": last,
            "input_span_ms": span, "input_complete": complete,
            "last_note_bpm": last_note_bpm, "last_setting_bpm": bpm,
            "tempo_changes": [{"at_ms": at, "bpm": value} for at, value in tempos],
            "capture_warnings": sorted(set(gaps + (["interrupted"] if interrupted else []) +
                                           (["held_notes"] if held or sustained else []))),
            "pad_used": any(e["type"] == "pad" and e.get("enabled") for e in events)}


class SessionStore:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "sessions.sqlite3"

    @contextmanager
    def database(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            r.require(version in (0, 1), "Unsupported session database version.")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, release TEXT NOT NULL,
                    target TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL,
                    summary TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_recording_per_task
                    ON sessions(task_id) WHERE status = 'recording';
                CREATE TABLE IF NOT EXISTS chunks (
                    session_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    midi BLOB NOT NULL, events TEXT NOT NULL, elapsed_ms REAL NOT NULL,
                    PRIMARY KEY(session_id, sequence)
                );
                PRAGMA user_version = 1;
            """)
            with connection:
                yield connection
        finally:
            connection.close()

    def start(self, task_id, session_id=None):
        # A client-chosen ID makes a lost start response safe to retry.
        session_id = session_id or "S-" + uuid.uuid4().hex
        r.require(isinstance(session_id, str) and r.re.fullmatch(r"S-[a-f0-9]{32}", session_id),
                  "Invalid session ID.")
        with r.log_lock(self.root), self.database() as db:
            existing = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if existing:
                r.require(existing["task_id"] == task_id, "This session ID belongs to another task.")
                return self.public(existing)
            task = next((t for t in r.records(r.read_events(self.root))
                         if t["assignment"]["task_id"] == task_id), None)
            r.require(task is not None and not task["report"] and not task["cancelled"], "An active task is required.")
            r.require(not db.execute("SELECT 1 FROM sessions WHERE task_id=? AND status='recording'",
                                     (task_id,)).fetchone(), "This task already has an open session. Recover the saved practice first.")
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,NULL)",
                       (session_id, task_id, task["assignment"]["release"], r.jdump(task["target"]),
                        datetime.now(timezone.utc).isoformat(), "recording"))
            return self.public(db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())

    @staticmethod
    def public(row):
        return {key: row[key] for key in ("id", "task_id", "release", "created_at", "status")} | {
            "summary": json.loads(row["summary"]) if row["summary"] else None}

    def list(self, task_id=None):
        if not self.path.exists():
            return []
        with self.database() as db:
            query = "SELECT * FROM sessions"
            params = ()
            if task_id:
                query += " WHERE task_id=?"
                params = (task_id,)
            rows = db.execute(query + " ORDER BY created_at,id", params).fetchall()
            result = []
            for row in rows:
                item = self.public(row)
                item["next_sequence"] = db.execute(
                    "SELECT COUNT(*) FROM chunks WHERE session_id=?", (row["id"],)).fetchone()[0]
                result.append(item)
            return result

    def append(self, session_id, packet):
        r.require(isinstance(packet, dict) and set(packet) == {"sequence", "midi", "events", "elapsed_ms"},
                  "Invalid recording packet format.")
        seq, elapsed, events = packet["sequence"], packet["elapsed_ms"], packet["events"]
        r.require(type(seq) is int and 0 <= seq < 100000, "Invalid packet sequence number.")
        r.number(elapsed, "elapsed_ms", 0, MAX_MS)
        r.require(isinstance(packet["midi"], str) and len(packet["midi"]) <= 3_000_000, "The MIDI packet is too large.")
        try:
            blob = base64.b64decode(packet["midi"], validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("Invalid MIDI encoding.") from exc
        for at, _, _ in midi_messages(blob):
            r.require(at <= elapsed, "The MIDI timestamp is outside the session duration.")
        r.require(isinstance(events, list) and len(events) <= 10000, "Invalid event list.")
        for event in events:
            r.require(isinstance(event, dict) and event.get("type") in EVENTS, "Unknown session event.")
            r.number(event.get("at_ms"), "event.at_ms", 0, elapsed)
            if event["type"] in ("play", "tempo"):
                r.number(event.get("bpm"), "event.bpm", 1, 400)
            if event["type"] in ("pad", "click"):
                r.require(type(event.get("enabled")) is bool, "The enabled flag must be a boolean.")
        event_text = r.jdump(events)
        r.require(len(event_text) <= 500_000, "The event data is too large.")
        with r.log_lock(self.root), self.database() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            r.require(row is not None, "Session not found.")
            previous = db.execute("SELECT * FROM chunks WHERE session_id=? AND sequence=?", (session_id, seq)).fetchone()
            if previous:
                r.require(previous["midi"] == blob and previous["events"] == event_text and previous["elapsed_ms"] == elapsed,
                          "A saved packet cannot be overwritten with different content.")
                return {"saved_sequence": seq, "duplicate": True}
            r.require(row["status"] == "recording", "Input cannot be added to a finished session.")
            count, last = db.execute("SELECT COUNT(*),MAX(elapsed_ms) FROM chunks WHERE session_id=?", (session_id,)).fetchone()
            r.require(seq == count and elapsed >= (last or 0), "Packets are out of order. Resend the earlier packets first.")
            db.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", (session_id, seq, blob, event_text, elapsed))
        return {"saved_sequence": seq, "duplicate": False}

    @staticmethod
    def chunks(db, session_id):
        return [{"midi": row["midi"], "events": json.loads(row["events"]), "elapsed_ms": row["elapsed_ms"]}
                for row in db.execute("SELECT * FROM chunks WHERE session_id=? ORDER BY sequence", (session_id,))]

    def finish(self, session_id, expected_chunks, interrupted=False):
        r.require(type(expected_chunks) is int and expected_chunks >= 0, "Invalid packet count.")
        r.require(type(interrupted) is bool, "The interrupted flag must be a boolean.")
        with r.log_lock(self.root), self.database() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            r.require(row is not None, "Session not found.")
            chunks = self.chunks(db, session_id)
            r.require(len(chunks) == expected_chunks, "Some recorded input has not reached the server yet.")
            if row["status"] == "recording":
                summary = measurements(chunks, interrupted)
                db.execute("UPDATE sessions SET status=?,summary=? WHERE id=?",
                           ("interrupted" if interrupted else "finished", r.jdump(summary), session_id))
            return self.public(db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())

    def export(self, session_id):
        r.require(self.path.exists(), "Session not found.")
        with self.database() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            r.require(row is not None, "Session not found.")
            chunks = self.chunks(db, session_id)
            metadata = self.public(row) | {"format": "jazz-midi-1", "target": json.loads(row["target"]),
                                          "events": [e for c in chunks for e in c["events"]]}
            return b"JPM1" + b"".join(c["midi"] for c in chunks), metadata
