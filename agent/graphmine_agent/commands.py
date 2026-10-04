"""Local research commands. None of these enter the model conversation."""

from .models import ChatResponse, FeedbackCreate, LLMMode

HELP = (
    "Local commands (both / and \\ work):\n"
    "/feedback note [| expected answer] — flag an issue\n"
    "/correct expected answer — save a correction\n"
    "/rate 1–5 [note] — rate the last answer\n"
    "/note observation — save a research note\n"
    "/export — download this session and its evidence\n"
    "/status — show the model version\n"
    "/help — show these commands\n"
    "Commands are stored locally and never sent to the model. Annotations need review before training."
)


def command_name(message):
    words = message.strip().split(maxsplit=1)
    first = words[0] if words else ""
    return first[1:].lower() if first.startswith(("/", "\\")) else None


def dispatch(database, settings, session_id, request, previous):
    command = command_name(request.message)
    parts = request.message.strip().split(maxsplit=1)
    text = parts[1].strip() if len(parts) == 2 else ""

    def reply(message, **extra):
        return ChatResponse(
            mode=LLMMode.analyst, command=command, message=message, **extra
        )

    if command == "help":
        return reply(HELP)
    if command == "export":
        return reply(
            "Session archive ready. It includes the conversation, uploaded data, results, model calls and feedback.",
            download_url=f"/api/sessions/{session_id}/history/archive",
        )
    if command == "status":
        router = settings.active_routing_model
        return reply(
            f"Version: {settings.deployment_version}\nAnalysis selection: {router}\nPlanning and answers: {settings.llm_model}"
        )
    if command not in {"feedback", "correct", "rate", "note"}:
        return reply("Unknown local command. Nothing was sent to the model.\n" + HELP)
    if not text:
        return reply("Add a note after the command.\n" + HELP)
    wrong, separator, expected = text.partition("|")
    values = {
        "what_went_wrong": wrong.strip(),
        "expected_behavior": expected.strip() or None,
        "category": "feedback",
    }
    if command == "correct":
        values.update(
            what_went_wrong="User supplied a corrected answer",
            expected_behavior=text,
            category="correction",
        )
    elif command == "note":
        values.update(what_went_wrong=text, expected_behavior=None, category="note")
    elif command == "rate":
        score, _, note = text.partition(" ")
        if score not in {"1", "2", "3", "4", "5"}:
            return reply(
                "Use /rate 1 to 5, optionally followed by a note. No model call was made."
            )
        values.update(
            what_went_wrong=note.strip() or f"User rated this answer {score}/5",
            expected_behavior=None,
            category="rating",
            rating=int(score),
        )
    elif not wrong.strip() or (separator and not expected.strip()):
        return reply(
            "Use /feedback your note, optionally followed by | what you expected."
        )
    prior_response = (
        previous["data"] if previous and previous["type"] == "chat.response" else {}
    )
    job_id, result_id = prior_response.get("job_id"), prior_response.get("result_id")
    if job_id:
        result_id = database.get_job(job_id).result_id
    feedback = database.add_feedback(
        session_id,
        FeedbackCreate(
            **values,
            turn_id=previous["turn_id"] if previous else None,
            job_id=job_id,
            result_id=result_id if previous else request.result_id,
        ),
    )
    return reply(
        "Saved with this conversation for later review. No model call was made.",
        feedback_id=feedback.id,
    )
