"""Revision-bound reviews and portable analytics evidence for Dataset Studio."""
from copy import deepcopy
import json
import sys


def content_of(ex):
    return {k: ex.get(k) for k in ("schema", "adapter", "split", "turns", "prompts", "output", "deleted", "analytics", "source_studio")}


class Reviews:
    def _host(self):
        return sys.modules[type(self).__module__]

    def _check_revisions(self, ids, expected):
        if not isinstance(expected, dict) or set(expected) != set(ids):
            raise LookupError("Reload the examples before saving: expected revisions are required")
        for rid in ids:
            if rid not in self.ids():
                raise KeyError(rid)
            revision = expected[rid]
            if type(revision) is not int or revision != self._revisions.get(rid, 0):
                raise LookupError("An example changed in another view; reload before saving or exporting")

    def _content_hash(self, ex):
        return self._host().digest(content_of(ex))

    def _review_current(self, ex):
        proof = ex.get("review_proof") or {}
        return ex.get("review") == "approved" and proof.get("content_sha256") == self._content_hash(ex)

    def _analytics_error(self, ex):
        if not ex.get("analytics"):
            return None
        try:
            from graphmine_agent.analytics_studio import validate_bundle
            row = validate_bundle(ex["analytics"])
            if ex["schema"] != row["schema"] or ex["adapter"] != "workflow":
                return "Imported analytics schema or training adapter changed"
            question = {p["path"]: p["value"] for p in ex["prompts"]}.get("question")
            if ex["output"] != row["output"] or question != row["question"] or ex["turns"]:
                return "Content changed after execution review; import a newly executed and reviewed workflow before training export"
        except Exception as exc:
            return f"Analytics evidence could not be verified: {exc}"
        return None

    def import_analytics(self, raw):
        ACTOR, utc_now = self._host().ACTOR, self._host().utc_now
        from graphmine_agent.analytics_studio import MAX_BYTES, validate_bundle
        if not isinstance(raw, str) or len(raw.encode()) > MAX_BYTES:
            raise ValueError("Choose a GraphMine Studio exchange JSON file of at most 4 MiB")
        bundle = json.loads(raw)
        try:
            row = validate_bundle(bundle)
        except Exception as exc:
            raise ValueError(f"Invalid analytics exchange: {exc}") from exc
        with self.lock:
            for ex in self.all_effective():
                if (ex.get("analytics") or {}).get("sha256") == bundle["sha256"]:
                    return {"example": ex, "issues": {}, "reused": True}
            from uuid import uuid4
            rid = f"studio-{uuid4().hex[:12]}"
            state = {"schema": row["schema"], "adapter": "workflow", "split": "train", "group": rid,
                     "prompt_fields": [{"path": "question", "label": "User question", "value": row["question"]}],
                     "output": row["output"], "turns": [], "analytics": deepcopy(bundle),
                     "source_authorship": deepcopy(row["authorship"]),
                     "imported_by": getattr(ACTOR, "name", None), "imported_at": utc_now()}
            self._write("import-analytics", rid, state)
            self._recompute_issues()
            return {"example": self.effective(rid), "issues": self._issues}

    def _prepare_review(self, rid, state, patch):
        ACTOR, utc_now = self._host().ACTOR, self._host().utc_now
        ex = self.effective(rid, state_override=state)
        if patch.get("review") == "approved":
            issues = self.validate(ex)
            error = next((i["message"] for i in issues if i["level"] == "error"), None)
            if error:
                raise ValueError(f"Fix this example before approving: {error}")
            state["review_proof"] = {"content_sha256": self._content_hash(ex),
                                     "revision": self._revisions.get(rid, 0) + 1,
                                     "by": getattr(ACTOR, "name", None), "at": utc_now()}
            state["review"] = "approved"
        elif patch.get("review") is not None:
            state.pop("review_proof", None)
        return state
