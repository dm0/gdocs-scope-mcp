"""Internal rich_text.preparation responsibilities."""


from dataclasses import dataclass, field

from gdocs_scope_mcp.rich_text.compiler import gpars_to_requests
from gdocs_scope_mcp.rich_text.plans import TableInsertionPlan


@dataclass
class PreparedInsertion:
    """Keep planned requests and report uploads left behind after cleanup."""

    requests: list[dict] | TableInsertionPlan
    cleanup_pending: list[str] = field(default_factory=list)
    paragraphs: list = field(default_factory=list)

    def recompile(self, newline_before: bool):
        """Change boundary breaks while retaining already-staged image URLs."""
        requests = gpars_to_requests(
            self.paragraphs, newline_before=newline_before,
        )
        old = (self.requests.iter_requests()
               if isinstance(self.requests, TableInsertionPlan)
               else self.requests)
        new = (requests.iter_requests()
               if isinstance(requests, TableInsertionPlan) else requests)
        sources = [r['insertInlineImage']['uri'] for r in old
                   if 'insertInlineImage' in r]
        images = [r['insertInlineImage'] for r in new
                  if 'insertInlineImage' in r]
        for image, uri in zip(images, sources, strict=True):
            if isinstance(requests, TableInsertionPlan):
                # Body requests are generated on demand; update blocks too.
                requests.replace_image_uri(image['uri'], uri)
            else:
                image['uri'] = uri
        return requests
