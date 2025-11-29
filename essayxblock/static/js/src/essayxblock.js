/* essayxblock/static/js/src/essayxblock.js */

function EssayXBlock(runtime, element, initArgs) {
    // XBlock runtime + jQuery
    var $ = window.jQuery || window.$;

    // Config passed from student_view
    var mode = initArgs.mode || "practice";
    var minWords = initArgs.min_words || 0;
    var maxWords = initArgs.max_words || 0;
    var maxChars = initArgs.max_chars || 0;
    var maxAttempts = initArgs.max_attempts || 1;
    var attemptsUsed = initArgs.attempts_used || 0;
    var showScoreInExam = !!initArgs.show_score_in_exam;

    // DOM elements
    var $root = $(element);
    var $textarea = $root.find(".essayxblock-textarea");
    var $wordCurrent = $root.find(".essayxblock-word-current");
    var $wordMax = $root.find(".essayxblock-word-max");
    var $charCurrent = $root.find(".essayxblock-char-current");
    var $attemptsUsed = $root.find(".essayxblock-attempts-used");
    var $attemptsMax = $root.find(".essayxblock-attempts-max");
    var $submitBtn = $root.find(".essayxblock-submit-button");
    var $feedback = $root.find(".essayxblock-feedback");

    // Set initial display values
    $wordMax.text(maxWords || "");
    $attemptsUsed.text(attemptsUsed);
    $attemptsMax.text(maxAttempts);

    // Handler URL for backend proxy
    var submitUrl = runtime.handlerUrl(element, "submit_essay");

    // ----------------- Toolbar (cut/copy/paste) ----------------------------

    // Build a simple toolbar that sits under the textarea
    var $toolbar = $(
        '<div class="essayxblock-toolbar">' +
            '<button type="button" class="essayxblock-btn essayxblock-btn-cut">Cut</button>' +
            '<button type="button" class="essayxblock-btn essayxblock-btn-copy">Copy</button>' +
            '<button type="button" class="essayxblock-btn essayxblock-btn-paste">Paste</button>' +
        "</div>"
    );
    $textarea.after($toolbar);

    var $btnCut = $toolbar.find(".essayxblock-btn-cut");
    var $btnCopy = $toolbar.find(".essayxblock-btn-copy");
    var $btnPaste = $toolbar.find(".essayxblock-btn-paste");

    // ----------------- Helpers ----------------------------

    function escapeHtml(text) {
        return String(text || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function countWords(text) {
        if (!text) return 0;
        var trimmed = text.trim();
        if (!trimmed) return 0;
        // Simple word split on whitespace
        return trimmed.split(/\s+/).length;
    }

    function updateCounts() {
        var text = $textarea.val() || "";
        var words = countWords(text);
        var chars = text.length;

        $wordCurrent.text(words);
        $charCurrent.text(chars);

        // Simple visual hint when exceeding limits (no hard blocking here)
        if (maxWords && words > maxWords) {
            $wordCurrent.addClass("essayxblock-count-exceeded");
        } else {
            $wordCurrent.removeClass("essayxblock-count-exceeded");
        }

        if (maxChars && chars > maxChars) {
            $charCurrent.addClass("essayxblock-count-exceeded");
        } else {
            $charCurrent.removeClass("essayxblock-count-exceeded");
        }
    }

    function setSubmitting(isSubmitting) {
        if (isSubmitting) {
            $root.addClass("essayxblock-block-loading");
            $submitBtn.prop("disabled", true);
            $submitBtn.text("Submitting...");
        } else {
            $root.removeClass("essayxblock-block-loading");
            $submitBtn.prop("disabled", false);
            $submitBtn.text("Submit essay");
        }
    }

    function showMessage(message, isError) {
        var cls = isError ? "essayxblock-msg-error" : "essayxblock-msg-info";
        $feedback
            .empty()
            .append($("<div>").addClass(cls).text(message));
    }

    // More robust + debug logging
    function buildHighlightedHtml(text, spans) {
        console.log("EssayXBlock: building highlighted HTML", {
            textPreview: (text || "").slice(0, 80),
            spans: spans
        });

        if (!text) {
            return "<p><em>No essay text to display.</em></p>";
        }

        // If no spans, just escape the entire text
        if (!spans || !spans.length) {
            return "<p>" + escapeHtml(text) + "</p>";
        }

        // Sort spans by start index
        spans = spans.slice().sort(function (a, b) {
            var as = a.start || 0;
            var bs = b.start || 0;
            return as - bs;
        });

        var result = [];
        var cursor = 0;
        var len = text.length;

        for (var i = 0; i < spans.length; i++) {
            var span = spans[i] || {};
            var start = span.start || 0;
            var end = span.end || 0;
            var type = span.type || "generic";
            var msg = span.message || span.note || "";

            if (start < 0) start = 0;
            if (end < start) end = start;
            if (start > len) start = len;
            if (end > len) end = len;

            // Plain chunk before this span
            if (start > cursor) {
                var plainChunk = text.slice(cursor, start);
                result.push(escapeHtml(plainChunk));
            }

            // Highlighted chunk
            var chunk = text.slice(start, end);
            var cssClass = "essayxblock-error-" + type; // e.g., error-grammar
            var attrs = ' class="' + cssClass + '"';
            if (msg) {
                attrs += ' data-message="' + escapeHtml(msg) + '"';
                attrs += ' title="' + escapeHtml(msg) + '"';
            }

            result.push("<span" + attrs + ">" + escapeHtml(chunk) + "</span>");
            cursor = end;
        }

        // Remaining text
        if (cursor < len) {
            var tail = text.slice(cursor);
            result.push(escapeHtml(tail));
        }

        return "<p>" + result.join("") + "</p>";
    }

    function renderLegend(legend) {
        if (!legend) return "";
        var html = ['<div class="essayxblock-legend"><strong>Legend:</strong>'];
        html.push("<ul>");
        for (var key in legend) {
            if (!Object.prototype.hasOwnProperty.call(legend, key)) continue;
            var item = legend[key] || {};
            var label = item.label || key;
            var cssClass = "essayxblock-legend-item-" + key;
            html.push(
                '<li class="' +
                    cssClass +
                    '"><span class="legend-color legend-' +
                    key +
                    '"></span> ' +
                    escapeHtml(label) +
                    "</li>"
            );
        }
        html.push("</ul></div>");
        return html.join("");
    }

    function renderSuccess(result, originalText) {
        console.log("EssayXBlock: backend result", result);

        // Update attempts info from result
        attemptsUsed = result.attempts_used || attemptsUsed;
        $attemptsUsed.text(attemptsUsed);

        var isExam = (result.mode || mode) === "exam";
        var canShowScore = !isExam || showScoreInExam;

        // Score
        var scoreObj = result.score || {};
        var raw = scoreObj.raw;
        var normalized = scoreObj.normalized;
        var scaleMin = scoreObj.scale_min;
        var scaleMax = scoreObj.scale_max;

        var $content = $("<div>").addClass("essayxblock-feedback-inner");

        if (canShowScore) {
            var scoreText = "";
            if (raw !== undefined && raw !== null) {
                scoreText = "Score: " + raw;
                if (scaleMax !== undefined && scaleMax !== null) {
                    scoreText += " / " + scaleMax;
                }
            } else if (normalized !== undefined && normalized !== null) {
                var pct = Math.round(normalized * 100);
                scoreText = "Score: " + pct + "%";
            } else {
                scoreText = "Score available.";
            }

            $content.append(
                $("<div>")
                    .addClass("essayxblock-score")
                    .text(scoreText)
            );
        }

        if (isExam) {
            // In exam mode, we keep feedback minimal
            var examMsg = "Your submission has been recorded.";

            if (!canShowScore) {
                examMsg += " Score and detailed feedback are hidden in exam mode.";
            } else {
                examMsg += " Detailed feedback is hidden in exam mode.";
            }

            $content.append(
                $("<div>")
                    .addClass("essayxblock-msg-info")
                    .text(examMsg)
            );

            $feedback.empty().append($content);

            if ($feedback.length && $feedback[0].scrollIntoView) {
                $feedback[0].scrollIntoView({ behavior: "smooth", block: "start" });
            }
            return;
        }

        // Practice mode: show categories, feedback, highlights
        var categories = result.categories || [];
        if (categories.length) {
            var $table = $('<table class="essayxblock-categories"></table>');
            var $thead = $("<thead>");
            $thead.append(
                "<tr><th>Category</th><th>Score</th><th>Comment</th></tr>"
            );
            $table.append($thead);

            var $tbody = $("<tbody>");
            categories.forEach(function (cat) {
                var label = cat.label || cat.id || "";
                var rawScore = cat.raw;
                var rowScore =
                    rawScore !== undefined && rawScore !== null ? rawScore : "";
                var comment = cat.comment || "";

                var $tr = $("<tr>");
                $tr.append($("<td>").text(label));
                $tr.append($("<td>").text(rowScore));
                $tr.append($("<td>").text(comment));
                $tbody.append($tr);
            });
            $table.append($tbody);
            $content.append($table);
        }

        var feedbackObj = result.feedback || {};
        if (feedbackObj.summary) {
            $content.append(
                $("<div>")
                    .addClass("essayxblock-summary")
                    .append(
                        $("<h4>").text("Overall feedback"),
                        $("<p>").text(feedbackObj.summary)
                    )
            );
        }

        if (feedbackObj.strengths && feedbackObj.strengths.length) {
            var $ulS = $('<ul class="essayxblock-strengths-list"></ul>');
            feedbackObj.strengths.forEach(function (s) {
                $ulS.append($("<li>").text(s));
            });
            $content.append(
                $("<div>")
                    .addClass("essayxblock-strengths")
                    .append($("<h4>").text("Strengths"), $ulS)
            );
        }

        if (feedbackObj.improvements && feedbackObj.improvements.length) {
            var $ulI = $('<ul class="essayxblock-improvements-list"></ul>');
            feedbackObj.improvements.forEach(function (imp) {
                $ulI.append($("<li>").text(imp));
            });
            $content.append(
                $("<div>")
                    .addClass("essayxblock-improvements")
                    .append($("<h4>").text("Areas for improvement"), $ulI)
            );
        }

        // Color-coded essay (practice mode only)
        var annotations =
            result.annotations ||
            result.annotation || // be lenient if backend uses singular
            {};
        var spans = annotations.spans || annotations.marks || [];
        var legend = annotations.legend || {};

        var $essaySection = $("<div>").addClass("essayxblock-highlighted-essay");
        $essaySection.append($("<h4>").text("Annotated essay"));

        // Build highlighted HTML
        var highlightedHtml = buildHighlightedHtml(originalText, spans);
        $essaySection.append(
            $('<div class="essayxblock-highlighted-text"></div>').html(
                highlightedHtml
            )
        );

        // Legend or "no issues" message
        if (spans && spans.length) {
            var legendHtml = renderLegend(legend);
            if (legendHtml) {
                $essaySection.append(
                    $('<div class="essayxblock-legend-container"></div>').html(
                        legendHtml
                    )
                );
            }
        } else {
            $essaySection.append(
                $('<div class="essayxblock-no-issues"></div>').text(
                    "No specific issues were highlighted in your essay."
                )
            );
        }

        $content.append($essaySection);

        // Optional model essay
        if (feedbackObj.model_essay) {
            var $model = $("<div>").addClass("essayxblock-model-essay");
            $model.append($("<h4>").text("Sample high-scoring essay"));
            $model.append(
                $("<pre>")
                    .addClass("essayxblock-model-text")
                    .text(feedbackObj.model_essay)
            );
            $content.append($model);
        }

        $feedback.empty().append($content);

        // Smooth scroll feedback into view
        if ($feedback.length && $feedback[0].scrollIntoView) {
            $feedback[0].scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    function renderError(resultOrMsg) {
        if (typeof resultOrMsg === "string") {
            showMessage(resultOrMsg, true);
        } else {
            var err = (resultOrMsg && resultOrMsg.error) || {};
            var code = err.code || "";
            var msg =
                err.message ||
                "We couldn't score your essay right now. Please try again later.";

            if (code === "BACKEND_TIMEOUT" && !msg) {
                msg = "Scoring took too long. Please try again or shorten your essay.";
            }

            showMessage(msg, true);

            // If we've hit max attempts, disable submit
            if (code === "MAX_ATTEMPTS_REACHED") {
                $submitBtn.prop("disabled", true);
            }
        }

        if ($feedback.length && $feedback[0].scrollIntoView) {
            $feedback[0].scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    // ----------------- Toolbar actions (cut / copy / paste) -----------------

    function selectAllText() {
        $textarea.focus();
        $textarea[0].setSelectionRange(0, $textarea.val().length);
    }

    $btnCopy.on("click", function () {
        var text = $textarea.val() || "";
        if (!text) return;

        // Try Clipboard API first
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard
                .writeText(text)
                .catch(function () {
                    try {
                        selectAllText();
                        document.execCommand("copy");
                    } catch (e) {
                        console.warn("Copy failed", e);
                    }
                });
        } else {
            try {
                selectAllText();
                document.execCommand("copy");
            } catch (e) {
                console.warn("Copy failed", e);
            }
        }
    });

    $btnCut.on("click", function () {
        var text = $textarea.val() || "";
        if (!text) return;

        // Copy first
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard
                .writeText(text)
                .catch(function () {
                    try {
                        selectAllText();
                        document.execCommand("copy");
                    } catch (e) {
                        console.warn("Cut copy failed", e);
                    }
                });
        } else {
            try {
                selectAllText();
                document.execCommand("copy");
            } catch (e) {
                console.warn("Cut copy failed", e);
            }
        }

        // Then clear textarea
        $textarea.val("");
        updateCounts();
    });

    $btnPaste.on("click", function () {
        if (navigator.clipboard && navigator.clipboard.readText) {
            navigator.clipboard
                .readText()
                .then(function (clipText) {
                    if (!clipText) return;
                    var current = $textarea.val() || "";
                    $textarea.val(current + (current ? " " : "") + clipText);
                    updateCounts();
                })
                .catch(function (e) {
                    console.warn("Paste failed", e);
                });
        } else {
            console.warn("Clipboard read not supported in this browser.");
        }
    });

    // ----------------- Event bindings ----------------------

    $textarea.on("input", function () {
        updateCounts();
    });

    $submitBtn.on("click", function () {
        var text = $textarea.val() || "";

        // Client-side empty check (server will also check)
        if (!text.trim()) {
            showMessage("Please type your essay before submitting.", true);
            return;
        }

        // Optional soft check for min words
        var wc = countWords(text);
        if (minWords && wc < minWords) {
            showMessage(
                "Your essay is too short. Minimum is " + minWords + " words.",
                true
            );
            // Still allow them to submit if they want:
            // return; // uncomment to hard-block
        }

        // Optional check for attempts (JS side; server also enforces)
        if (attemptsUsed >= maxAttempts) {
            renderError({
                error: {
                    code: "MAX_ATTEMPTS_REACHED",
                    message:
                        "You have already used all available attempts for this question."
                }
            });
            return;
        }

        setSubmitting(true);
        showMessage("Submitting your essay for scoring...", false);

        $.ajax({
            type: "POST",
            url: submitUrl,
            data: JSON.stringify({ essay_text: text }),
            contentType: "application/json; charset=utf-8",
            dataType: "json"
        })
            .done(function (result) {
                if (result && result.status === "ok") {
                    renderSuccess(result, text);
                } else {
                    renderError(result);
                }
            })
            .fail(function (jqXHR, textStatus, errorThrown) {
                console.error("EssayXBlock: AJAX error", {
                    jqXHR: jqXHR,
                    textStatus: textStatus,
                    errorThrown: errorThrown
                });
                var msg =
                    "Network error while submitting essay: " +
                    (textStatus || "") +
                    " " +
                    (errorThrown || "");
                renderError(msg);
            })
            .always(function () {
                setSubmitting(false);
            });
    });

    // Initial counts on page load
    updateCounts();
}
