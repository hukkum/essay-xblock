"""AI Essay scoring XBlock for practice and exam modes."""

import json
import uuid
import logging

import requests
from importlib.resources import files

from web_fragments.fragment import Fragment
from xblock.core import XBlock
from xblock.fields import (
    Boolean,
    Float,
    Integer,
    Scope,
    String,
)

logger = logging.getLogger(__name__)

class EssayXBlock(XBlock):
    """
    Essay XBlock that sends a student's essay to an external AI scoring backend,
    stores the results, and publishes a grade to Open edX.

    - Practice mode: allow multiple attempts, show full feedback (front-end logic).
    - Exam mode: limit attempts, hide detailed feedback (front-end logic).

    The backend contract is documented in the project and expects:
      { "meta": {...}, "config": {...}, "prompt": {...}, "essay": {...} }
    """

    # ----- XBlock grading configuration --------------------------------------

    has_score = True
    icon_class = "problem"  # shows 'problem' icon in LMS

    # Points in the gradebook (e.g., 1.0, 10.0 etc.)
    weight = Float(
        default=1.0,
        scope=Scope.settings,
        help="Problem weight (points) for grading.",
    )

    # ----- Author-facing settings (same for all students) ---------------------

    # Optional student-facing prompt (can also be provided via separate HTML block)
    prompt_html = String(
        default=(
            "<p><strong>Sample essay prompt:</strong> "
            "Discuss the advantages and disadvantages of online learning compared to traditional classrooms.</p>"
        ),
        scope=Scope.settings,
        help="HTML instructions shown to students (essay topic).",
    )

    # Hidden AI instructions (not shown to students; sent to backend as 'prompt.instructions')
    ai_instructions = String(
        default=(
            "You are a PTE-style writing examiner. Evaluate the essay based on grammar, "
            "vocabulary, coherence & cohesion, and task response. "
            "Return a JSON object matching the config.scoring.categories ids and fields."
        ),
        scope=Scope.settings,
        help="Hidden instructions sent to the AI scoring backend.",
    )

    language = String(
        default="en",
        scope=Scope.settings,
        help="Language code of the essay (e.g., 'en' or 'en-US').",
    )

    min_words = Integer(
        default=150,
        scope=Scope.settings,
        help="Minimum recommended word count for the essay.",
    )

    max_words = Integer(
        default=250,
        scope=Scope.settings,
        help="Maximum allowed word count for the essay.",
    )

    max_chars = Integer(
        default=1500,
        scope=Scope.settings,
        help="Maximum allowed character count for the essay (0 = no limit).",
    )

    max_attempts = Integer(
        default=3,
        scope=Scope.settings,
        help="Maximum number of attempts allowed per student.",
    )

    # "practice" or "exam"
    mode = String(
        default="practice",
        scope=Scope.settings,
        help="Mode for this problem: 'practice' (feedback) or 'exam' (minimal feedback).",
    )

    # Base URL of the backend API, e.g. "http://localhost:5001/api"
    api_base_url = String(
        default="http://localhost:5001/api/essay-score",
        scope=Scope.settings,
        help="Base URL of the scoring backend, e.g. 'http://localhost:5001/api'.",
    )

    # Whether to show numeric score to students in exam mode (UI will decide how to use this)
    show_score_in_exam = Boolean(
        default=True,
        scope=Scope.settings,
        help="If true, show numeric score to students in exam mode (but no detailed feedback).",
    )

    # ----- Per-student state --------------------------------------------------

    student_essay_text = String(
        default="",
        scope=Scope.user_state,
        help="Last submitted essay text by this student.",
    )

    student_score = Float(
        default=0.0,
        scope=Scope.user_state,
        help="Last computed score (scaled by weight).",
    )

    student_attempt_count = Integer(
        default=0,
        scope=Scope.user_state,
        help="Number of successful scoring attempts used by this student.",
    )

    # Store full backend response as JSON string so we can re-render feedback
    last_result_json = String(
        default="",
        scope=Scope.user_state,
        help="Last backend response JSON (as string) for this student.",
    )

    # ----- Helpers ------------------------------------------------------------

    def resource_string(self, path: str) -> str:
        """Handy helper for getting resources from our package."""
        return files(__package__).joinpath(path).read_text(encoding="utf-8")

    # ----- XBlock views -------------------------------------------------------

    def student_view(self, context=None):
        """
        Primary student view: renders HTML skeleton and loads JS/CSS.

        The JS will:
        - Display prompt_html
        - Show textarea + word counter
        - Submit essays via the 'submit_essay' handler
        - Render feedback based on backend JSON and self.mode
        """
        html = self.resource_string("static/html/essayxblock.html")

        # Pass minimal context via string formatting; JS can fetch more via an init payload.
        frag = Fragment(html.format(self=self))
        frag.add_css(self.resource_string("static/css/essayxblock.css"))
        frag.add_javascript(self.resource_string("static/js/src/essayxblock.js"))

        # Provide initial configuration to JS
        init_args = {
            "mode": self.mode,
            "min_words": self.min_words,
            "max_words": self.max_words,
            "max_chars": self.max_chars,
            "max_attempts": self.max_attempts,
            "attempts_used": self.student_attempt_count,
            "show_score_in_exam": self.show_score_in_exam,
            "has_previous_result": bool(self.last_result_json),
        }
        frag.initialize_js("EssayXBlock", json_args=init_args)
        return frag

    # ----- Backend integration & grading --------------------------------------

    def _build_backend_payload(self, essay_text: str, attempt_index: int) -> dict:
        """
        Build the JSON payload expected by the scoring backend.
        """
        # Fallbacks for IDs in different runtimes (LMS vs workbench)
        request_id = str(uuid.uuid4())

        try:
            xblock_id = str(self.scope_ids.usage_id)
        except Exception:  # pragma: no cover - defensive
            xblock_id = "essayxblock-unknown"

        course_id = getattr(self.runtime, "course_id", "course-v1:WORKBENCH+DEMO+2025")
        user_id = getattr(self.runtime, "anonymous_student_id", "anon-student")

        # Basic counts (backend will recompute and validate as well)
        text = essay_text or ""
        char_count = len(text)
        word_count = len(text.split()) if text.strip() else 0

        payload = {
            "meta": {
                "api_version": "1.0",
                "request_id": request_id,
                "xblock_id": xblock_id,
                "course_id": str(course_id),
                "user_id": str(user_id),
                "mode": self.mode,
            },
            "config": {
                "language": self.language,
                "limits": {
                    "min_words": self.min_words,
                    "max_words": self.max_words,
                    "max_chars": self.max_chars,
                },
                "scoring": {
                    "scale_min": 0,
                    "scale_max": 100,
                    "normalize": True,
                    "categories": [
                        {"id": "grammar", "label": "Grammar", "weight": 0.25},
                        {"id": "vocabulary", "label": "Vocabulary", "weight": 0.25},
                        {
                            "id": "coherence",
                            "label": "Coherence & Cohesion",
                            "weight": 0.25,
                        },
                        {"id": "task_response", "label": "Task Response", "weight": 0.25},
                    ],
                },
            },
            "prompt": {
                "instructions": self.ai_instructions,
                "task_type": "argumentative",
                "topic_id": "pte_essay_01",
            },
            "essay": {
                "text": text,
                "word_count": word_count,
                "char_count": char_count,
                "attempt_index": attempt_index,
                "max_attempts": self.max_attempts,
            },
        }
        return payload

    def _call_backend(self, payload: dict) -> dict:
        """
        Call the external scoring backend and return its JSON response.

        Any network / parsing errors are converted to a uniform local error response.
        """
        url = (self.api_base_url or "").strip()

        if not url:
            logger.error("EssayXBlock: api_base_url is not configured")
            return {
                "status": "error",
                "status_code": 500,
                "request_id": payload["meta"]["request_id"],
                "error": {
                    "code": "BACKEND_URL_NOT_CONFIGURED",
                    "message": "Scoring service URL is not configured.",
                    "details": {},
                },
            }

        logger.info(
            "EssayXBlock: calling backend",
            extra={
                "url": url,
                "request_id": payload["meta"]["request_id"],
            },
        )

        try:
            resp = requests.post(url, json=payload, timeout=200)
        except requests.RequestException as exc:
            logger.exception(
                "EssayXBlock: network error calling backend",
                extra={
                    "url": url,
                    "request_id": payload["meta"]["request_id"],
                },
            )
            return {
                "status": "error",
                "status_code": 503,
                "request_id": payload["meta"]["request_id"],
                "error": {
                    "code": "BACKEND_UNAVAILABLE",
                    "message": "Scoring service is currently unavailable. Please try again later.",
                    "details": {
                        "exception": str(exc),
                        "url": url,
                    },
                },
            }

        # Log raw HTTP result
        logger.info(
            "EssayXBlock: backend HTTP response",
            extra={
                "url": url,
                "request_id": payload["meta"]["request_id"],
                "status_code": resp.status_code,
                "text_preview": resp.text[:300],
            },
        )

        try:
            data = resp.json()
        except ValueError:
            logger.error(
                "EssayXBlock: backend returned non-JSON",
                extra={
                    "url": url,
                    "request_id": payload["meta"]["request_id"],
                    "status_code": resp.status_code,
                    "text_preview": resp.text[:300],
                },
            )
            return {
                "status": "error",
                "status_code": resp.status_code or 500,
                "request_id": payload["meta"]["request_id"],
                "error": {
                    "code": "INVALID_BACKEND_RESPONSE",
                    "message": "Scoring service returned an invalid response.",
                    "details": {
                        "text": resp.text[:500],
                        "url": url,
                    },
                },
            }

        # Normalize error if HTTP status is error
        if resp.status_code >= 400 and data.get("status") != "error":
            data.setdefault("status", "error")
            data.setdefault("status_code", resp.status_code)

        logger.info(
            "EssayXBlock: backend JSON parsed",
            extra={
                "url": url,
                "request_id": payload["meta"]["request_id"],
                "status": data.get("status"),
                "status_code": data.get("status_code", resp.status_code),
                "error_code": (data.get("error") or {}).get("code"),
            },
        )

        return data


    def _apply_grading(self, backend_result: dict) -> None:
        """
        Given a successful backend result (status == 'ok'), update user state
        and publish a grade event.
        """
        score_obj = backend_result.get("score") or {}
        raw = score_obj.get("raw")
        normalized = score_obj.get("normalized")
        scale_min = score_obj.get("scale_min", 0.0)
        scale_max = score_obj.get("scale_max", 1.0)

        if normalized is None and raw is not None:
            try:
                raw = float(raw)
                denom = float(scale_max) - float(scale_min)
                if denom > 0:
                    normalized = (raw - float(scale_min)) / denom
                else:
                    normalized = 0.0
            except Exception:  # pragma: no cover - defensive
                normalized = 0.0

        if normalized is None:
            normalized = 0.0

        # Store the score scaled by weight
        try:
            self.student_score = float(normalized) * float(self.weight)
        except Exception:  # pragma: no cover - defensive
            self.student_score = 0.0

        # Persist full result for later student_view rendering
        self.last_result_json = json.dumps(backend_result)

        # Publish grade to LMS
        self.runtime.publish(
            self,
            "grade",
            {
                "value": self.student_score,
                "max_value": float(self.weight),
            },
        )

    def max_score(self) -> float:
        """
        Required grading hook: the maximum score this problem can give (in gradebook points).
        """
        return float(self.weight)

    # ----- JSON handler called by front-end JS --------------------------------

    @XBlock.json_handler
    def submit_essay(self, data, suffix=""):
        """
        Handler invoked by front-end JS when the student submits an essay.

        Expects 'essay_text' in the incoming JSON.
        Returns:
          - On success: backend response + attempt info and XBlock mode.
          - On error: error object (do not increment attempts or grade).
        """
        # Basic data validation from request
        essay_text = (data or {}).get("essay_text", "")
        essay_text = essay_text or ""  # ensure string

        # If max attempts reached, short-circuit
        if self.student_attempt_count >= self.max_attempts:
            return {
                "status": "error",
                "status_code": 403,
                "error": {
                    "code": "MAX_ATTEMPTS_REACHED",
                    "message": "You have already used all available attempts for this question.",
                    "details": {
                        "attempts_used": self.student_attempt_count,
                        "max_attempts": self.max_attempts,
                    },
                },
                "mode": self.mode,
                "attempts_used": self.student_attempt_count,
                "max_attempts": self.max_attempts,
            }

        # Very minimal local validation to avoid calling backend on empty essays
        if not essay_text.strip():
            return {
                "status": "error",
                "status_code": 422,
                "error": {
                    "code": "EMPTY_ESSAY",
                    "message": "Please type your essay before submitting.",
                    "details": {},
                },
                "mode": self.mode,
                "attempts_used": self.student_attempt_count,
                "max_attempts": self.max_attempts,
            }

        # Build payload and call backend
        next_attempt_index = self.student_attempt_count + 1
        payload = self._build_backend_payload(essay_text, attempt_index=next_attempt_index)
        backend_result = self._call_backend(payload)

        # If backend returned an error, do not increment attempts or grade
        if backend_result.get("status") != "ok":
            # Just pass error through, plus context
            backend_result.setdefault("mode", self.mode)
            backend_result.setdefault("attempts_used", self.student_attempt_count)
            backend_result.setdefault("max_attempts", self.max_attempts)
            return backend_result

        # Successful scoring: update user state
        self.student_attempt_count = next_attempt_index
        self.student_essay_text = essay_text
        self._apply_grading(backend_result)

        # Return backend result plus extra context for the JS (mode, attempts)
        backend_result["mode"] = self.mode
        backend_result["attempts_used"] = self.student_attempt_count
        backend_result["max_attempts"] = self.max_attempts
        backend_result["show_score_in_exam"] = self.show_score_in_exam

        return backend_result

    # ----- Workbench scenarios ------------------------------------------------

    @staticmethod
    def workbench_scenarios():
        """
        Canned scenarios for display in the XBlock workbench.

        Provides:
        - A practice-mode essay block with 3 attempts
        - An exam-mode essay block with 1 attempt
        """
        return [
            (
                "EssayXBlock - Practice",
                """
                <vertical_demo>
                    <essayxblock
                        prompt_html="&lt;p&gt;&lt;strong&gt;Practice prompt:&lt;/strong&gt; Do you agree or disagree that technology has improved education?&lt;/p&gt;"
                        ai_instructions="You are a PTE-style examiner. Score on a 0-100 scale, and return grammar, vocabulary, coherence, and task_response scores."
                        language="en"
                        min_words="120"
                        max_words="200"
                        max_chars="1500"
                        max_attempts="3"
                        mode="practice"
                        api_base_url="http://localhost:5001/api/essay-score"
                        show_score_in_exam="true"
                        weight="1.0"
                    />
                </vertical_demo>
                """,
            ),
            (
                "EssayXBlock - Exam",
                """
                <vertical_demo>
                    <essayxblock
                        prompt_html="&lt;p&gt;&lt;strong&gt;Exam prompt:&lt;/strong&gt; Some people prefer living in cities, while others prefer rural areas. Discuss both views and give your opinion.&lt;/p&gt;"
                        ai_instructions="You are a strict exam grader. Score on a 0-100 scale and respond in the required JSON format."
                        language="en"
                        min_words="150"
                        max_words="250"
                        max_chars="1500"
                        max_attempts="1"
                        mode="exam"
                        api_base_url="http://localhost:5001/api/essay-score"
                        show_score_in_exam="true"
                        weight="1.0"
                    />
                </vertical_demo>
                """,
            ),
        ]
