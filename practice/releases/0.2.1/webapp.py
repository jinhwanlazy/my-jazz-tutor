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
        return {"title": "아직 결과가 없습니다.", "details": []}
    actual, checks = json.loads(report["actual_json"]), json.loads(report["checks_json"])
    details = []
    labels = {"notes_correct": "음", "steady_pulse": "박 유지", "no_stops": "무중단"}
    for key, label in labels.items():
        if checks.get(key) is not True:
            details.append(f"{label}: {'미충족으로 보고' if checks.get(key) is False else '아직 미확인'}")
    if not report["clean_runs"]:
        details.append("연속 성공 횟수가 아직 미확인입니다.")
    elif float(report["clean_runs"]) < target["criteria"]["min_clean_runs"]:
        details.append(f"연속 {target['criteria']['min_clean_runs']}회 성공 기준에 아직 못 미쳤습니다.")
    if any(actual.get(k) is None for k in r.SPEC):
        details.append("실제로 수행한 조건 중 확인하지 않은 항목이 있습니다.")
    if any(actual.get(k) is not None and
           (actual[k] < target[k] if k == "bpm" else actual[k] != target[k]) for k in r.SPEC):
        details.append("발급 조건과 실제 조건이 다릅니다. 실제 연습 내용은 그대로 보존했습니다.")
    if result == "success":
        details = ["자기보고로 지정 조건을 충족했습니다. 같은 날 다음 항목으로 이어갈 수 있습니다.",
                   "후일 같은 조건 재현과 MIDI 연주 검증은 별도입니다."]
    return {"title": {"success": "오늘의 조건을 충족했어요", "unmet": "다음 시도에서 조정해 봅시다",
                       "unknown": "확인된 내용부터 기록했어요"}[result],
            "details": details, "evidence": "self-report"}


class Application:
    def __init__(self, root, data, source=r.HERE):
        self.root, self.source, self.data = Path(root).resolve(), Path(source).resolve(), data
        if (self.source / "publish.py").exists():
            r.require(not self.root.is_relative_to((self.source.parent / "practice").resolve()),
                      "개발 웹 앱은 실제 practice에 연결할 수 없습니다. 임시 --practice-root를 사용하세요.")
        r.require(self.root.is_dir(), "연습 디렉터리가 없습니다.")
        self.preview = (self.source / "publish.py").exists()
        self.store = SessionStore(self.root)
        self.token = secrets.token_urlsafe(32)
        self.mutations = threading.RLock()

    def assert_active(self):
        if not self.preview:
            marker = self.root / "active-version"
            r.require(marker.exists() and marker.read_text().strip() == self.data["version"],
                      "활성 버전이 바뀌었습니다. 서버를 다시 시작하세요.")

    def state(self):
        events = r.read_events(self.root)
        tasks = r.records(events)
        lessons = []
        for lesson in self.data["exercises"]:
            eligible = [key for key in self.data["allowed_keys"]
                        if all(r.goal_successes(self.data, tasks, parent, key, self.data["default_bpm"])
                               for parent in lesson["prerequisites"])]
            lessons.append({**lesson, "eligible_keys": eligible,
                            "targets": {key: r.target_for(self.data, lesson["id"], key)
                                        for key in self.data["allowed_keys"]}})
        history = []
        for task in reversed(tasks):
            report = task["report"]
            history.append({"id": task["assignment"]["task_id"], "exercise_id": task["assignment"]["exercise_id"],
                            "assigned_at": task["assignment"]["recorded_at"], "target": task["target"],
                            "cancelled": task["cancelled"], "reason": (task["cancellation"] or task["assignment"])["reason"],
                            "report": report, "outcome": r.outcome(task), "feedback": feedback(task),
                            "revisions": [e for e in events if e["task_id"] == task["assignment"]["task_id"]
                                          and e["event_type"] in ("reported", "corrected")]})
        return {"csrf_token": self.token, "preview": self.preview,
                "workspace_id": hashlib.sha256(str(self.root).encode()).hexdigest()[:16],
                "status": r.status(self.root, self.data), "exercises": lessons,
                "keys": self.data["allowed_keys"], "minimum_bpm": self.data["minimum_bpm"],
                "maximum_bpm": self.data["maximum_bpm"], "arrangements": r.ARRANGEMENTS,
                "history": history, "sessions": self.store.list()}

    def post(self, path, payload):
        r.require(isinstance(payload, dict), "요청은 JSON object여야 합니다.")
        with self.mutations:
            self.assert_active()
            if path == "/api/assign":
                return r.assign(self.root, self.data, payload["exercise_id"], payload.get("key"),
                                payload.get("bpm"), "practice", payload.get("reason", "웹에서 선택한 연습"))
            if path in ("/api/report", "/api/cancel"):
                task_id = payload["task_id"]
                sessions = self.store.list(task_id)
                r.require(not any(s["status"] == "recording" for s in sessions), "진행 중인 연습을 먼저 종료·저장하세요.")
                if path == "/api/cancel":
                    r.require(not any(s["summary"] and (s["summary"]["active_ms"] > 0 or s["summary"]["note_ons"])
                                      for s in sessions), "연습한 내용이 있습니다. 취소 대신 결과를 기록하세요.")
                    return r.cancel(self.root, self.data, task_id, payload["reason"])
                correction = payload.get("correction", False)
                r.require(type(correction) is bool, "정정 여부가 잘못되었습니다.")
                result = r.record_result(self.root, self.data, task_id, payload["result"], correction)
                task = next(t for t in r.records(r.read_events(self.root)) if t["assignment"]["task_id"] == task_id)
                return result | {"feedback": feedback(task)}
            if path == "/api/sessions/start":
                return self.store.start(payload["task_id"], payload["session_id"])
            if path == "/api/sessions/chunk":
                return self.store.append(payload["session_id"], payload["packet"])
            if path == "/api/sessions/finish":
                return self.store.finish(payload["session_id"], payload["expected_chunks"], payload.get("interrupted", False))
            raise KeyError("없는 API 경로입니다.")


def make_server(root, data, port=8765, source=r.HERE):
    r.require(type(port) is int and 0 <= port <= 65535, "포트는 0~65535여야 합니다.")
    app = Application(root, data, source)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def permitted(self, mutation=False):
            port = self.server.server_address[1]
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            r.require(self.headers.get("Host") in hosts, "허용되지 않은 Host입니다.")
            origin = self.headers.get("Origin")
            r.require(not origin or origin in {f"http://{host}" for host in hosts}, "다른 사이트에서 접근할 수 없습니다.")
            if mutation:
                r.require(secrets.compare_digest(self.headers.get("X-Jazz-Token", ""), app.token),
                          "화면을 새로고침한 뒤 다시 시도하세요.")
                r.require(self.headers.get("Content-Type", "").split(";")[0] == "application/json", "JSON 요청이 필요합니다.")

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
                    r.require(len(parts) == 5 and r.re.fullmatch(r"S-[a-f0-9]{32}", parts[3]), "없는 녹음입니다.")
                    raw, metadata = app.store.export(parts[3])
                    if parts[4] == "midi":
                        self.respond(200, raw, "application/octet-stream", parts[3] + ".jpm")
                    elif parts[4] == "metadata":
                        self.respond(200, metadata, filename=parts[3] + ".json")
                    else:
                        self.respond(404, {"error": "없는 파일입니다."})
                else:
                    name = "webapp.html" if path == "/" else path.lstrip("/")
                    if name not in ASSETS:
                        self.respond(404, {"error": "없는 페이지입니다."})
                        return
                    self.respond(200, (app.source / name).read_bytes(), ASSETS[name])
            except (ValueError, KeyError, TypeError) as exc:
                self.respond(400, {"error": str(exc)})
            except (OSError, sqlite3.Error):
                self.respond(500, {"error": "파일을 읽지 못했습니다."})

        def do_POST(self):
            try:
                self.permitted(True)
                length = int(self.headers.get("Content-Length", "0"))
                r.require(0 < length <= 4_000_000, "요청 크기가 잘못되었습니다.")
                self.connection.settimeout(15)
                body = self.rfile.read(length)
                r.require(len(body) == length, "요청이 중간에 끊겼습니다.")
                payload = json.loads(body, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("유효하지 않은 숫자입니다.")))
                self.respond(200, app.post(urlsplit(self.path).path, payload))
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                self.respond(400, {"error": str(exc)})
            except (OSError, sqlite3.Error):
                self.respond(500, {"error": "저장하지 못했습니다. 연결을 확인하고 다시 시도하세요."})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.app = app
    return server


def serve(root, data, port=8765, open_browser=False):
    server = make_server(root, data, port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Jazz Piano Coach · {url}\n종료: Ctrl+C", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
