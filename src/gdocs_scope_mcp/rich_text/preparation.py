"""Internal rich_text.preparation responsibilities."""


from dataclasses import dataclass, field

from gdocs_scope_mcp.rich_text.plans import TableInsertionPlan


@dataclass
class PreparedInsertion:
    """Keep planned requests and report uploads left behind after cleanup."""

    requests: list[dict] | TableInsertionPlan
    cleanup_pending: list[str] = field(default_factory=list)
    paragraphs: list = field(default_factory=list)
