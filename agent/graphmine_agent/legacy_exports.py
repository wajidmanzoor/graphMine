"""Prepared downloads for classic answers and complete conversation evidence."""

import zipfile

from .export_streams import temporary, write_json
from .reporting import iter_report
from .result_index import is_workflow_index


def feedback_export(runtime, session_id):
    output = temporary()
    try:
        for item in runtime.database.iter_feedback(session_id):
            write_json(output, {
                "schema_version": "graphmine-feedback-v1", "review_status": "unreviewed",
                "automatically_used_for_training": False, "annotation": item.model_dump(mode="json"),
            })
            output.write(b"\n")
        runtime.database.get_session(session_id)
        return output
    except BaseException:
        output.close(); raise


def answer_report(runtime, result_id):
    result = runtime.database.get_result(result_id)
    output = temporary()
    try:
        for chunk in iter_report(result):
            output.write(chunk.encode("utf-8"))
        runtime.database.get_session(result.session_id)
        return output
    except BaseException:
        output.close(); raise


def history_archive(runtime, session_id):
    database, history = runtime.database, runtime.database.history
    database.get_session(session_id)
    # Snapshot existing source views on the preparation worker. The original
    # events and native evidence remain in the archive, including old revisions.
    history.snapshot(session_id, "conversation.json", database.conversation_transcript(session_id))
    history.snapshot(session_id, "session.json", database.get_session(session_id))
    history.snapshot(session_id, "analytics/events.json", database.events(session_id))
    workflows = runtime.analytics.list(session_id)
    history.snapshot(session_id, "analytics/workflows.json", workflows)
    output = temporary()
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            root = history.session_path(session_id)
            for item in history.manifest(session_id)["files"]:
                path = root / item["path"]
                if path.resolve().is_relative_to(root.resolve()):
                    bundle.write(path, f"{session_id}/{item['path']}")
            for row in workflows:
                directory = runtime.analytics.root / row["id"]
                for path in sorted(directory.rglob("*")):
                    if path.is_file() and path.resolve().is_relative_to(directory.resolve()) and not is_workflow_index(path):
                        bundle.write(path, f"{session_id}/analytics/{directory.name}/{path.relative_to(directory)}")
        database.get_session(session_id)
        return output
    except BaseException:
        output.close(); raise
