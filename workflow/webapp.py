"""Loopback-only web UI over the same versioned practice operations as the CLI."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import urlsplit
import webbrowser

import review as r
from sessions import SessionStore

ASSETS = {"webapp.html": "text/html", "webapp.css": "text/css", "webapp.js": "text/javascript",
          "audio.mjs": "text/javascript", "capture.mjs": "text/javascript"}


def feedback(task):
    result = r.outcome(task)
    report, target = task["report"], task["target"]
    if report is None:
        return {"title": "No result reported yet.", "details": []}
    actual, checks = json.loads(report["actual_json"]), json.loads(report["checks_json"])
    details = []
    labels = {"notes_correct": "Notes", "steady_pulse": "Steady pulse", "no_stops": "No stops"}
    for key, label in labels.items():
        if checks.get(key) is not True:
            details.append(f"{label}: {'Reported as unmet' if checks.get(key) is False else 'Not yet confirmed'}")
    if not report["clean_runs"]:
        details.append("The number of consecutive successful runs is still unknown.")
    elif float(report["clean_runs"]) < target["criteria"]["min_clean_runs"]:
        details.append(f"The requirement of {target['criteria']['min_clean_runs']} consecutive successful runs has not been met yet.")
    if any(actual.get(k) is None for k in r.SPEC):
        details.append("Some actual practice conditions are still unconfirmed.")
    if any(actual.get(k) is not None and
           (actual[k] < target[k] if k == "bpm" else actual[k] != target[k]) for k in r.SPEC):
        details.append("Actual conditions differ from the assignment. Your reported practice has been preserved.")
    if result == "success":
        details = ["Your self-report meets the assigned criteria. You can continue to another exercise today.",
                   "Later retention and MIDI performance verification are separate observations."]
    return {"title": {"success": "You met the assigned criteria", "unmet": "Adjust your next attempt",
                       "unknown": "The confirmed details are recorded"}[result],
            "details": details, "evidence": "self-report"}


class Application:
    def __init__(self, root, data, source=r.HERE):
        self.root, self.source, self.data = Path(root).resolve(), Path(source).resolve(), data
        if (self.source / "publish.py").exists():
            r.require(not self.root.is_relative_to((self.source.parent / "practice").resolve()),
                      "Development previews cannot use production practice data. Set --practice-root to a temporary directory.")
        r.require(self.root.is_dir(), "The practice directory does not exist.")
        self.preview = (self.source / "publish.py").exists()
        self.revision = None if self.preview else json.loads((self.source / "manifest.json").read_text())["revision"]
        self.store = SessionStore(self.root)
        self.token = secrets.token_urlsafe(32)
        self.mutations = threading.RLock()

    def assert_active(self):
        if not self.preview:
            marker = self.root / "runtime.json"
            r.require(marker.exists() and json.loads(marker.read_text()).get("revision") == self.revision,
                      "The active runtime has changed. Restart the server.")

    def state(self):
        events = r.read_events(self.root)
        tasks = r.records(events)
        lessons = []
        for lesson in self.data["exercises"]:
            eligible = [key for key in self.data["allowed_keys"]
                        if all(r.goal_successes(self.data, tasks, parent, key, self.data["default_bpm"])
                               for parent in lesson["prerequisites"])]
            lessons.append({**r.display_builtin(lesson), "eligible_keys": eligible,
                            "targets": {key: r.display_builtin(r.target_for(self.data, lesson["id"], key))
                                        for key in self.data["allowed_keys"]}})
        history = []
        for task in reversed(tasks):
            report = task["report"]
            history.append({"id": task["assignment"]["task_id"], "exercise_id": task["assignment"]["exercise_id"],
                            "assigned_at": task["assignment"]["recorded_at"], "target": r.display_builtin(task["target"]),
                            "cancelled": task["cancelled"], "reason": (task["cancellation"] or task["assignment"])["reason"],
                            "report": report, "outcome": r.outcome(task), "feedback": feedback(task),
                            "revisions": [e for e in events if e["task_id"] == task["assignment"]["task_id"]
                                          and e["event_type"] in ("reported", "corrected")]})
        status = r.status(self.root, self.data)
        if "target" in status["next"]:
            status["next"]["target"] = r.display_builtin(status["next"]["target"])
        return {"csrf_token": self.token, "preview": self.preview,
                "workspace_id": hashlib.sha256(str(self.root).encode()).hexdigest()[:16],
                "status": status, "exercises": lessons,
                "keys": self.data["allowed_keys"], "minimum_bpm": self.data["minimum_bpm"],
                "maximum_bpm": self.data["maximum_bpm"], "arrangements": r.ARRANGEMENTS,
                "history": history, "sessions": self.store.list()}

    def post(self, path, payload):
        r.require(isinstance(payload, dict), "The request must be a JSON object.")
        with self.mutations:
            self.assert_active()
            if path == "/api/assign":
                return r.assign(self.root, self.data, payload["exercise_id"], payload.get("key"),
                                payload.get("bpm"), "practice", payload.get("reason", "Practice selected in the web app"))
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
                return result | {"feedback": feedback(task)}
            if path == "/api/sessions/start":
                return self.store.start(payload["task_id"], payload["session_id"])
            if path == "/api/sessions/chunk":
                return self.store.append(payload["session_id"], payload["packet"])
            if path == "/api/sessions/finish":
                return self.store.finish(payload["session_id"], payload["expected_chunks"], payload.get("interrupted", False))
            raise KeyError("Unknown API path.")


def make_server(root, data, port=8765, source=r.HERE):
    r.require(type(port) is int and 0 <= port <= 65535, "The port must be between 0 and 65535.")
    app = Application(root, data, source)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def permitted(self, mutation=False):
            port = self.server.server_address[1]
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            r.require(self.headers.get("Host") in hosts, "Host not allowed.")
            origin = self.headers.get("Origin")
            r.require(not origin or origin in {f"http://{host}" for host in hosts}, "Access from another site is not allowed.")
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
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
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
                    self.respond(200, app.state())
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
                    self.respond(200, (app.source / name).read_bytes(), ASSETS[name])
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
                self.respond(200, app.post(urlsplit(self.path).path, payload))
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                self.respond(400, {"error": str(exc)})
            except (OSError, sqlite3.Error):
                self.respond(500, {"error": "Could not save. Check the connection and try again."})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.app = app
    return server


def serve(root, data, port=8765, open_browser=False):
    server = make_server(root, data, port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"My Jazz Tutor · {url}\nStop: Ctrl+C", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
