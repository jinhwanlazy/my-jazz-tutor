"""Local web UI with explicit LAN binding, using the same operations as the CLI."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
from pathlib import Path
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

import review as r
from notation import score_for
from sessions import SessionStore, reflection_measurements
from attempts import AttemptStore, recording_coverage
from recommendation import Recommendations, ERRORS, repeat
from localization import Translations, ERRORS as TRANSLATION_ERRORS
from difficulty import task_characteristics

ASSETS = {"webapp.html": "text/html", "webapp.css": "text/css", "webapp.js": "text/javascript",
          "audio.mjs": "text/javascript", "capture.mjs": "text/javascript",
          "i18n.mjs": "text/javascript", "translations.json": "application/json",
          "score.mjs": "text/javascript", "timeline.mjs": "text/javascript",
          "abc-view.mjs": "text/javascript", "abcjs.min.js": "text/javascript",
          "midi-analysis.mjs": "text/javascript", "attempt-audio.mjs": "text/javascript",
          "midi-analysis-worker.mjs": "text/javascript", "backing.mjs": "text/javascript",
          "midi-controls.mjs": "text/javascript",
          "Bravura.woff2": "font/woff2", "Bravura-LICENSE.txt": "text/plain"}


def display_target(target, language, translations=None):
    score = score_for(target)
    presentation = {'notation': score, 'task_characteristics': task_characteristics(score)}
    if target.get("kind") == "generated" and translations is not None:
        display, state = translations.view(target, language)
        if state.get("error_code"):
            state["error"] = r.web_text(TRANSLATION_ERRORS.get(state["error_code"], TRANSLATION_ERRORS["connection"]), language)
        return display | presentation | {"translation": state}
    return (target if target.get("kind") == "generated" else r.display_builtin(target, language)) | presentation


def feedback(task, language="en"):
    text = lambda message, **values: r.web_text(message, language, **values)
    result = r.outcome(task)
    report, target = task["report"], task["target"]
    if report is None:
        return {"title": text("No result reported yet."), "details": []}
    if report["difficulty"] in r.RATINGS:
        return {"title": text("Practice saved"), "details": [], "evidence": "subjective difficulty"}
    actual, checks = json.loads(report["actual_json"]), json.loads(report["checks_json"])
    details = []
    labels = {"notes_correct": "Notes", "steady_pulse": "Steady pulse", "no_stops": "No stops"}
    for key, label in labels.items():
        if checks.get(key) is not True:
            details.append(text("{label}: {state}", label=text(label),
                                state=text("Reported as unmet" if checks.get(key) is False else "Not yet confirmed")))
    if not report["clean_runs"]:
        details.append(text("The number of consecutive successful runs is still unknown."))
    elif float(report["clean_runs"]) < target["criteria"]["min_clean_runs"]:
        details.append(text("The requirement of {runs} consecutive successful runs has not been met yet.",
                            runs=target['criteria']['min_clean_runs']))
    fields = {"key": "Key", "bpm": "Tempo", "bars": "Bar count", "arrangement": "Hand arrangement",
              "rhythm": "Rhythm", "bass": "Bass", "voicing": "Voicing", "melody": "Melody",
              "material_id": "Practice material"}
    missing = [text(fields[key]) for key in r.SPEC if actual.get(key) is None]
    if missing:
        details.append(text("Unconfirmed conditions: {fields}.", fields=", ".join(missing)))
        details.append(text("If you followed the assigned conditions, confirm that in the report form."))
    if any(actual.get(k) is not None and
           (actual[k] < target[k] if k == "bpm" else actual[k] != target[k]) for k in r.SPEC):
        details.append(text("Actual conditions differ from the assignment. Your reported practice has been preserved."))
    if result == "success":
        details = [text("Your self-report meets the assigned criteria. You can continue to another exercise today."),
                   text("Later retention and MIDI performance verification are separate observations.")]
    if result == "unknown":
        details.insert(0, text("This practice is recorded. Add any missing details you remember to assess the target."))
    return {"title": text({"success": "You met the assigned criteria", "unmet": "Adjust your next attempt",
                          "unknown": "Practice saved · assessment pending"}[result]),
            "details": details, "evidence": "self-report"}


class PlaybackSettings:
    """Workspace-wide preferences, separate from task BPM and performance evidence."""
    DEFAULTS = {'metronome_enabled':False, 'pad_enabled':False, 'drums_enabled':False,
                'click_volume':.35, 'pad_volume':.18, 'drum_volume':.18, 'drum_feel':'straight'}

    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root/'playback-settings.json'

    @classmethod
    def validate(cls, values, partial=False):
        r.require(isinstance(values,dict) and set(values) <= cls.DEFAULTS.keys()
                  and (partial or set(values) == cls.DEFAULTS.keys()), 'Invalid playback settings.')
        for key,value in values.items():
            if key.endswith('_enabled'):
                r.require(type(value) is bool, 'Playback switches must be boolean.')
            elif key == 'drum_feel':
                r.require(value in ('straight','swing'), 'Invalid drum feel.')
            else:
                r.require(type(value) in (int,float) and math.isfinite(value) and 0 <= value <= (1 if key=='click_volume' else .6),
                          'Playback volume is out of range.')

    def read(self):
        if not self.path.exists():
            return {'schema_version':1,'revision':0,'values':dict(self.DEFAULTS)}
        saved = json.loads(self.path.read_text())
        r.require(isinstance(saved,dict) and set(saved)=={'schema_version','revision','values'} and saved['schema_version']==1
                  and type(saved['revision']) is int and saved['revision']>=0, 'Invalid saved playback settings. Original file was preserved.')
        self.validate(saved['values'])
        return saved

    def update(self, changes):
        self.validate(changes,partial=True)
        with r.log_lock(self.root):
            current = self.read()
            values = current['values'] | changes
            if values == current['values']:
                return current
            saved = {'schema_version':1,'revision':current['revision']+1,'values':values}
            r.atomic_text(self.path,r.jdump(saved)+'\n')
            return saved


class Application:
    def __init__(self, root, data, source=r.HERE, recommender=None, translator=None):
        self.root, self.source, self.data = Path(root).resolve(), Path(source).resolve(), data
        if (self.source / "publish.py").exists():
            r.require(not self.root.is_relative_to((self.source.parent / "practice").resolve()),
                      "Development previews cannot use production practice data. Set --practice-root to a temporary directory.")
        r.require(self.root.is_dir(), "The practice directory does not exist.")
        self.preview = (self.source / "publish.py").exists()
        self.revision = None if self.preview else json.loads((self.source / "manifest.json").read_text())["revision"]
        self.store = SessionStore(self.root)
        self.attempts = AttemptStore(self.root)
        self.playback_settings = PlaybackSettings(self.root)
        self.token = secrets.token_urlsafe(32)
        self.mutations = threading.RLock()
        self.recommendations = Recommendations(self.root, data, recommender)
        self.translations = Translations(self.root, translator)

    def assert_active(self):
        if not self.preview:
            marker = self.root / "runtime.json"
            r.require(marker.exists() and json.loads(marker.read_text()).get("revision") == self.revision,
                      "The active runtime has changed. Restart the server.")

    def state(self, language="en"):
        events = r.read_events(self.root)
        tasks = r.visible_records(events)
        profile_path = self.root / "profile.json"
        profile = json.loads(profile_path.read_text()) if profile_path.exists() else {}
        task_ids = {t['assignment']['task_id'] for t in tasks}
        sessions = [s for s in self.store.list() if s['task_id'] in task_ids]
        attempts = self.attempts.list()
        history = []
        for task in reversed(tasks):
            report = task["report"]
            task_sessions = [s for s in sessions if s["task_id"] == task["assignment"]["task_id"]]
            started = any(s["status"] == "recording" or s["summary"] and (s["summary"]["active_ms"] > 0 or s["summary"]["note_ons"]) for s in task_sessions)
            history.append({"id": task["assignment"]["task_id"], "exercise_id": task["assignment"]["exercise_id"],
                            "assigned_at": task["assignment"]["recorded_at"], "target": display_target(task["target"], language, self.translations),
                            "cancelled": task["cancelled"], "retired": task["retired"], "discarded": task["discarded"],
                            "discard_choice": r.discard_details(task)["choice"],
                            "reason": r.discard_details(task)["note"] if task["discarded"] else (task["cancellation"] or task["assignment"])["reason"],
                            "report": report, "outcome": r.outcome(task), "feedback": feedback(task, language),
                            "completion": task["completion"], "completed": not r.is_pending(task) and bool(r.practice_record(task)) and not task['cancelled'],
                            "lifecycle_event_id": task['lifecycle_event_id'], "reopening": task.get('reopening'),
                            "revision_event_id": task['revision_event_id'],
                            "completions": task.get('completions', []),
                            "attempts": [a for a in attempts if a['task_id'] == task['assignment']['task_id']],
                            "assessment": self.attempts.summary(task, attempts),
                            "recording_coverage": recording_coverage(task, sessions, attempts),
                            "started": bool(started), "pending": r.is_pending(task),
                            "observations": r.reflection_observations(r.practice_record(task)) if r.practice_record(task) else reflection_measurements(task_sessions, profile),
                            "revisions": [e for e in events if e["task_id"] == task["assignment"]["task_id"]
                                          and e["event_type"] in ("reported", "corrected")]})
        status = r.status(self.root, self.data)
        if "target" in status["next"]:
            status["next"]["target"] = display_target(status["next"]["target"], language, self.translations)
        status["next"]["reason"] = r.web_text(status["next"]["reason"], language)
        status["evidence"] = r.web_text(status["evidence"], language)
        job = self.recommendations.latest()
        if job and job.get("error_code"):
            job["error"] = r.web_text(ERRORS[job["error_code"]], language)
        return {"csrf_token": self.token, "preview": self.preview, "language": language,
                "workspace_id": hashlib.sha256(str(self.root).encode()).hexdigest()[:16],
                "status": status, "recommendation": job,
                "minimum_bpm": 20, "maximum_bpm": 240, "arrangements": r.display_builtin(r.ARRANGEMENTS, language),
                "history": history, "sessions": sessions, "playback_settings": self.playback_settings.read()}

    def post(self, path, payload, language="en"):
        r.require(isinstance(payload, dict), "The request must be a JSON object.")
        with self.mutations:
            self.assert_active()
            if path == '/api/playback-settings':
                r.require(set(payload)=={'changes'}, 'Invalid playback settings request.')
                return self.playback_settings.update(payload['changes'])
            if path == "/api/recommend":
                r.require(set(payload) <= {"request_id", "request"}, "The recommendation request contains unknown fields.")
                return self.recommendations.start(payload["request_id"], language, payload.get("request", ""))
            if path == "/api/translate":
                r.require(set(payload) <= {"task_id", "retry"}, "The translation request contains unknown fields.")
                return self.translations.start(payload["task_id"], language, payload.get("retry", False))
            if path == "/api/repeat":
                r.require(set(payload) == {"source_task_id", "task_id"}, "Invalid repeat request.")
                return repeat(self.root, self.data, payload["source_task_id"], payload["task_id"])
            if path == "/api/assign":
                return r.assign(self.root, self.data, payload["exercise_id"], payload.get("key"),
                                payload.get("bpm"), "practice", payload.get("reason", "Practice selected in the web app"), payload.get("task_id"))
            if path == "/api/complete":
                r.require(set(payload) <= {'task_id','expected_event_id','manual_confirmed','attempt_id'}, 'Invalid completion request.')
                return self.attempts.complete(self.data, payload['task_id'], payload.get('expected_event_id'),
                                              payload.get('manual_confirmed', False), payload.get('attempt_id'))
            if path == '/api/reopen':
                r.require(set(payload) == {'task_id','expected_event_id'}, 'Invalid reopen request.')
                return r.reopen(self.root, self.data, payload['task_id'], payload['expected_event_id'])
            if path == '/api/delete':
                r.require(set(payload) == {'task_id','expected_event_id'}, 'Invalid deletion request.')
                return r.delete_practice(self.root, self.data, payload['task_id'], payload['expected_event_id'])
            if path == '/api/attempts/start':
                r.require(set(payload) <= {'task_id','attempt_id','bpm','manual','latency_ms'}, 'Invalid attempt request.')
                return self.attempts.start(payload['task_id'], payload['attempt_id'], payload['bpm'],
                                           payload.get('manual', False), payload.get('latency_ms', 0))
            if path == "/api/reflection":
                r.require(set(payload) <= {"task_id", "rating", "note", "expected_event_id"}, "The feedback contains unknown fields.")
                task = next((t for t in r.records(r.read_events(self.root)) if t['assignment']['task_id'] == payload['task_id']), None)
                r.require(task is not None and not r.is_pending(task), 'Complete the practice before leaving feedback.')
                return self.store.reflect(self.data, payload["task_id"], payload.get("rating"),
                                          payload.get("note", ""), payload.get("expected_event_id"))
            if path == "/api/discard":
                r.require(set(payload) <= {"task_id", "reason", "choice"}, "The discard request contains unknown fields.")
                return r.discard(self.root, self.data, payload["task_id"], payload.get("reason", ""), payload.get("choice", ""))
            if path in ("/api/report", "/api/cancel"):
                task_id = payload["task_id"]
                sessions = self.store.list(task_id)
                r.require(not any(s["status"] == "recording" for s in sessions), "Finish and save the current practice session first.")
                if path == "/api/cancel":
                    r.require(not any(s["summary"] and (s["summary"]["active_ms"] > 0 or s["summary"]["note_ons"])
                                      for s in sessions), "This task has been practiced. Report the result instead of cancelling it.")
                    return r.cancel(self.root, self.data, task_id, payload["reason"])
                correction = payload.get("correction", False)
                r.require(type(correction) is bool, "The correction flag must be a boolean.")
                result = r.record_result(self.root, self.data, task_id, payload["result"], correction)
                task = next(t for t in r.records(r.read_events(self.root)) if t["assignment"]["task_id"] == task_id)
                return result | {"feedback": feedback(task, language)}
            if path == "/api/sessions/start":
                return self.store.start(payload["task_id"], payload["session_id"])
            if path == "/api/sessions/chunk":
                return self.store.append(payload["session_id"], payload["packet"])
            if path == "/api/sessions/finish":
                result = self.store.finish(payload["session_id"], payload["expected_chunks"], payload.get("interrupted", False))
                attempt = self.attempts.finish_session(payload['session_id'])
                return result | ({'attempt': attempt} if attempt else {})
            raise KeyError("Unknown API path.")


def listen_host(host):
    r.require(isinstance(host, str), "The host must be an IPv4 address or localhost.")
    if host.lower() == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        raise ValueError("The host must be an IPv4 address or localhost (use 0.0.0.0 for LAN access).") from None
    r.require(not address.is_multicast and address != ipaddress.IPv4Address("255.255.255.255"),
              "The host must be a unicast IPv4 address or 0.0.0.0.")
    return str(address)


def make_server(root, data, port=8765, source=r.HERE, recommender=None, host="127.0.0.1", translator=None):
    r.require(type(port) is int and 0 <= port <= 65535, "The port must be between 0 and 65535.")
    host = listen_host(host)
    app = Application(root, data, source, recommender, translator)

    class Handler(BaseHTTPRequestHandler):
        def language(self):
            requested = parse_qs(urlsplit(self.path).query).get("lang", ["en"])[0]
            return requested if requested in ("en", "ko") else "en"

        def log_message(self, *_):
            pass

        def permitted(self, mutation=False):
            port = self.server.server_address[1]
            # A wildcard listener accepts the IP this connection actually reached,
            # never an arbitrary Host/DNS name supplied by the browser.
            local_ip = self.connection.getsockname()[0]
            names = {local_ip}
            if ipaddress.IPv4Address(local_ip).is_loopback:
                names.add("localhost")
            hosts = {f"{name}:{port}" for name in names}
            if port == 80:
                hosts.update(names)
            authorities = self.headers.get_all("Host", [])
            r.require(len(authorities) == 1 and authorities[0].lower() in hosts, "Host not allowed.")
            authority = authorities[0].lower()
            origins = self.headers.get_all("Origin", [])
            expected = {f"http://{authority}"}
            if port == 80:
                expected = {f"http://{authority.removesuffix(':80')}", f"http://{authority.removesuffix(':80')}:80"}
            r.require(len(origins) <= 1 and (not origins or origins[0].lower() in expected),
                      "Access from another site is not allowed.")
            if mutation:
                r.require(secrets.compare_digest(self.headers.get("X-Jazz-Token", ""), app.token),
                          "Refresh the page and try again.")
                r.require(self.headers.get("Content-Type", "").split(";")[0] == "application/json", "A JSON request is required.")

        def respond(self, status, body, content_type="application/json", filename=None):
            if content_type == "application/json":
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type != "application/octet-stream" else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            # Only abcjs 6.7.2's fixed measurement/drag CSS is permitted inline.
            # No general unsafe-inline exemption, scripts remain same-origin.
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-hashes' "
                             "'sha256-slvAeoOzvy3mPbO4szWUPitqjQh5R3Jihl2M50J2Zgk=' "
                             "'sha256-BCpnf71gZdCsSCHDzyB1RsBbZ0qQdqseK6v+yJsgg30='; "
                             "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                self.permitted()
                path = urlsplit(self.path).path
                if path == "/api/state":
                    self.respond(200, app.state(self.language()))
                elif path == '/api/playback-settings':
                    self.respond(200, app.playback_settings.read())
                elif path.startswith('/api/attempts/'):
                    self.respond(200, app.attempts.details(path.removeprefix('/api/attempts/')))
                elif path.startswith("/api/recommendations/"):
                    request_id = path.removeprefix("/api/recommendations/")
                    artifact = app.recommendations._path(request_id)
                    self.respond(200, json.loads(artifact.read_text()), filename=request_id + ".json")
                elif path.startswith("/api/recordings/"):
                    parts = path.split("/")
                    r.require(len(parts) == 5 and r.re.fullmatch(r"S-[a-f0-9]{32}", parts[3]), "Recording not found.")
                    raw, metadata = app.store.export(parts[3])
                    if parts[4] == "midi":
                        self.respond(200, raw, "application/octet-stream", parts[3] + ".jpm")
                    elif parts[4] == "metadata":
                        self.respond(200, metadata, filename=parts[3] + ".json")
                    else:
                        self.respond(404, {"error": "File not found."})
                else:
                    name = "webapp.html" if path == "/" else path.lstrip("/")
                    if name not in ASSETS:
                        self.respond(404, {"error": "Page not found."})
                        return
                    content = (app.source / name).read_bytes()
                    if ASSETS[name] == "application/json":
                        content = json.loads(content)
                    self.respond(200, content, ASSETS[name])
            except (ValueError, KeyError, TypeError) as exc:
                self.respond(400, {"error": str(exc)})
            except (OSError, sqlite3.Error):
                self.respond(500, {"error": "Could not read the file."})

        def do_POST(self):
            try:
                self.permitted(True)
                length = int(self.headers.get("Content-Length", "0"))
                r.require(0 < length <= 4_000_000, "Invalid request size.")
                self.connection.settimeout(15)
                body = self.rfile.read(length)
                r.require(len(body) == length, "The request was interrupted.")
                payload = json.loads(body, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Invalid number.")))
                self.respond(200, app.post(urlsplit(self.path).path, payload, self.language()))
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                self.respond(400, {"error": str(exc)})
            except (OSError, sqlite3.Error):
                self.respond(500, {"error": "Could not save. Check the connection and try again."})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.app = app
    return server


def serve(root, data, port=8765, open_browser=False, host="127.0.0.1"):
    server = make_server(root, data, port, host=host)
    address = server.server_address[0]
    browser_host = "127.0.0.1" if address == "0.0.0.0" else address
    url = f"http://{browser_host}:{server.server_address[1]}"
    print(f"My Jazz Tutor · {url}\nStop: Ctrl+C", flush=True)
    if not ipaddress.IPv4Address(address).is_loopback:
        print(f"Listening on {address}:{server.server_address[1]} · use this computer's LAN IP from other devices.\n"
              "LAN access has no login: reachable devices can access practice data and request recommendations.\n"
              "MIDI input requires HTTPS or localhost; metronome practice also works over LAN HTTP.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
