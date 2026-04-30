from __future__ import annotations

"""
考试中心最小联调回归脚本（本地 mock 上游）。

用途：
- 改动 exam_center 前后，快速验证关键链路是否回归。
- 避免再次出现 answers 结构 / attempt_id / 状态文案语义相关低级错误。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webapp import create_app, db
import webapp.routes as routes
from webapp.models import ExamCenterActivity, ExamCenterActivityDetail, ExamCenterAssignment


def run() -> None:
    app = create_app()
    state = {
        "assignments": {},
        "next_assignment": 100,
        "next_attempt": 500,
    }

    def fake_quiz(path: str, method: str = "GET", payload=None, query=None, timeout_seconds=None):
        payload = payload or {}
        if path.startswith("quiz/sets/") and path.endswith("/publish") and method == "POST":
            set_id = path.split("/")[2]
            return 200, {"code": 0, "message": "ok", "data": {"code": 0, "status": "published", "set_id": set_id}}

        if path == "quiz/assignments" and method == "POST":
            aid = str(state["next_assignment"])
            state["next_assignment"] += 1
            title = payload.get("title") or payload.get("name") or f"任务-{aid}"
            set_id = str(payload.get("set_id") or payload.get("setId") or "")
            rec = {"assignment_id": aid, "title": title, "set_id": set_id}
            state["assignments"][aid] = rec
            return 200, {"code": 0, "message": "ok", "data": {"code": 0, "data": rec}}

        if path in ("quiz/student/assignments", "quiz/me/assignments", "quiz/student/exams") and method == "GET":
            items = [{"assignment_id": k, "title": v["title"], "set_id": v["set_id"]} for k, v in state["assignments"].items()]
            return 200, {"code": 0, "message": "ok", "data": {"code": 0, "data": {"assignments": items}}}

        if path.startswith("quiz/exams/") and path.endswith("/start") and method == "POST":
            assignment_id = path.split("/")[2]
            if assignment_id not in state["assignments"]:
                return 404, {"code": "NOT_FOUND", "message": "assignment not found", "data": None}
            attempt_id = state["next_attempt"]
            state["next_attempt"] += 1
            return 200, {
                "code": 0,
                "message": "ok",
                "data": {
                    "code": 0,
                    "data": {
                        "attempt_id": attempt_id,
                        "assignment_id": assignment_id,
                        "questions": [
                            {"question_id": "q1", "stem": "题1", "options": [{"id": "A", "text": "甲"}]},
                            {"question_id": "q2", "stem": "题2", "options": [{"id": "B", "text": "乙"}]},
                        ],
                    },
                },
            }

        if path == "quiz/practice/submit" and method == "POST":
            if not isinstance(payload.get("answers"), list):
                return 422, {"code": "BAD", "message": "answers must be list", "data": None}
            if not (payload.get("attempt_id") or payload.get("attemptId") or (query or {}).get("attempt_id")):
                return 422, {"code": "BAD", "message": "attempt_id required", "data": None}
            return 200, {"code": 0, "message": "ok", "data": {"code": 0, "score": 82, "max_score": 100}}

        if path.startswith("quiz/exams/") and path.endswith("/submit") and method == "POST":
            if not isinstance(payload.get("answers"), list):
                return 422, {"code": "BAD", "message": "answers must be list", "data": None}
            return 200, {"code": 0, "message": "ok", "data": {"code": 0, "score": 76, "max_score": 100}}

        if path == "quiz/stats/overview" and method == "GET":
            return 503, {"code": "UPSTREAM_DOWN", "message": "down", "data": None}
        if path in ("quiz/stats/options", "quiz/stats/recent-activity") and method == "GET":
            return 503, {"code": "UPSTREAM_DOWN", "message": "down", "data": None}

        if path.startswith("quiz/stats/exam/") and method == "GET":
            return 404, {"code": "NOT_MOCKED", "message": "no upstream exam stats", "data": None}

        return 404, {"code": "NOT_MOCKED", "message": f"{method} {path}", "data": None}

    routes._quiz_api_call = fake_quiz

    with app.app_context():
        ExamCenterActivityDetail.query.delete()
        ExamCenterActivity.query.delete()
        ExamCenterAssignment.query.delete()
        db.session.commit()

    checks: list[str] = []
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["page13_authenticated"] = True
            s["display_name"] = "老师A"
            s["username"] = "teacher_a"

        r = c.post("/api/exam-center/teacher/sets/publish", json={"set_id": "set-100"})
        assert r.status_code == 200, r.get_json()
        checks.append("teacher_sync_set")

        r = c.post(
            "/api/exam-center/teacher/assignments",
            json={"set_id": "set-100", "title": "【测试】Smoke 考试任务", "due_date": "2030-12-31"},
        )
        j = r.get_json()
        aid = ((j.get("aiword") or {}).get("assignment") or {}).get("assignment_id")
        assert r.status_code == 200 and aid, j
        checks.append("teacher_create_assignment")

        with c.session_transaction() as s:
            s.pop("page13_authenticated", None)
            s["user_id"] = "stu-1"
            s["username"] = "stu_login"
            s["display_name"] = "学生甲"

        r = c.get("/api/exam-center/student/assignments")
        arr = ((r.get_json().get("data") or {}).get("assignments") or [])
        hit = next((x for x in arr if str(x.get("id")) == str(aid)), None)
        assert hit is not None, r.get_json()
        assert hit.get("due_at"), r.get_json()
        checks.append("student_assignments_visible")

        r = c.post("/api/exam-center/student/exams/start", json={"assignment_id": str(aid)})
        attempt_id = (((r.get_json().get("data") or {}).get("data") or {}).get("attempt_id"))
        assert r.status_code == 200 and attempt_id is not None, r.get_json()
        checks.append("student_start_exam")

        r = c.post("/api/exam-center/student/practice/submit", json={"session_id": "701", "answers": {"p1": "A"}})
        assert r.status_code == 200, r.get_json()
        checks.append("practice_submit_normalized")

        r = c.post(
            "/api/exam-center/student/exams/submit",
            json={"attempt_id": str(attempt_id), "assignment_id": str(aid), "answers": {"q1": "A"}},
        )
        assert r.status_code == 200, r.get_json()
        checks.append("exam_submit_normalized")

        with c.session_transaction() as s:
            s["page13_authenticated"] = True
            s["display_name"] = "老师A"
            s["username"] = "teacher_a"
        r = c.get(f"/api/exam-center/stats/exam/{aid}")
        sj = r.get_json() or {}
        dc = ((sj.get("data") or {}).get("deadline_completion")) or {}
        assert r.status_code == 200 and dc.get("on_time_count") == 1 and dc.get("late_count") == 0, sj
        checks.append("stats_exam_deadline_local")

        with c.session_transaction() as s:
            s.pop("page13_authenticated", None)
            s["user_id"] = "stu-1"
            s["username"] = "stu_login"
            s["display_name"] = "学生甲"

        r = c.get("/api/exam-center/student/history")
        recs = ((r.get_json().get("data") or {}).get("records") or [])
        assert recs and all("score" in x for x in recs), r.get_json()
        checks.append("history_scored")

        with c.session_transaction() as s:
            s["page13_authenticated"] = True
        r = c.get("/api/exam-center/stats/overview")
        d = (r.get_json() or {}).get("data") or {}
        assert "pass_score" in d and "pass_count" in d and "pass_rate_percent" in d, r.get_json()
        checks.append("stats_pass_metrics")

        r = c.get("/api/exam-center/stats/students")
        assert r.status_code == 200, r.get_json()
        rows = ((r.get_json() or {}).get("data") or {}).get("rows")
        assert isinstance(rows, list) and len(rows) >= 1, r.get_json()
        checks.append("stats_students_table")

        r = c.get("/api/exam-center/stats/students_by_mode")
        assert r.status_code == 200, r.get_json()
        rows2 = ((r.get_json() or {}).get("data") or {}).get("rows")
        assert isinstance(rows2, list) and len(rows2) >= 2, r.get_json()
        assert any(str(x.get("mode")) == "exam" for x in rows2 if isinstance(x, dict)), r.get_json()
        checks.append("stats_students_by_mode")
        r_alt = c.get("/api/exam-center/stats/students-by-mode")
        assert r_alt.status_code == 200, r_alt.get_json()
        checks.append("stats_students_by_mode_hyphen_alias")

    print("ALL_OK", ",".join(checks))


if __name__ == "__main__":
    run()

