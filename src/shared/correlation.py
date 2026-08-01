import uuid
from contextvars import ContextVar

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    return correlation_id_var.get()


def set_correlation_id(cid: str | None = None) -> str:
    if cid:
        correlation_id_var.set(cid)
    else:
        cid = uuid.uuid4().hex[:16]
        correlation_id_var.set(cid)
    return cid


def reset_correlation_id() -> None:
    correlation_id_var.set("")
