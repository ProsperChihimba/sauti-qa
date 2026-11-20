"""String enums. Stored as plain VARCHAR so adding a value never needs a migration."""

from enum import StrEnum


class Role(StrEnum):
    admin = "admin"
    analyst = "analyst"


class CallSource(StrEnum):
    upload = "upload"
    inbox = "inbox"
    api = "api"


class CallStatus(StrEnum):
    received = "received"
    preparing = "preparing"
    transcribing = "transcribing"
    labelling = "labelling"
    scoring = "scoring"
    done = "done"
    failed = "failed"


class ReviewStatus(StrEnum):
    not_required = "not_required"
    pending = "pending"
    in_review = "in_review"
    reviewed = "reviewed"


class Speaker(StrEnum):
    agent = "agent"
    customer = "customer"
    unknown = "unknown"


class Answer(StrEnum):
    yes = "yes"
    no = "no"
    na = "na"


class EvalTrigger(StrEnum):
    pipeline = "pipeline"
    rescore = "rescore"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class JobKind(StrEnum):
    prepare = "prepare"
    transcribe = "transcribe"
    label = "label"
    score = "score"
    export = "export"


class ExportKind(StrEnum):
    excel = "excel"
    csv = "csv"
    dataset = "dataset"


class NoteKind(StrEnum):
    note = "note"
    coaching = "coaching"
