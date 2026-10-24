"""Define strict input contracts for MCP edits before Google API access."""

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

NonemptyText = Annotated[str, Field(strict=True, min_length=1)]
ReplacementOccurrence = Annotated[int, Field(strict=True, ge=0)]
PositiveInteger = Annotated[int, Field(strict=True, ge=1)]


class Replacement(BaseModel):
    """Validate one replacement; an empty replacement deletes matched text."""

    model_config = ConfigDict(strict=True, extra='forbid')

    find: NonemptyText
    replace: str
    occurrence: ReplacementOccurrence = 1
    regex: bool = False

    @model_validator(mode='after')
    def validate_pattern(self) -> Self:
        """Reject invalid regular expressions before reading the document."""
        if self.regex:
            try:
                re.compile(self.find)
            except re.error as error:
                raise ValueError(
                    'find must be a valid regular expression',
                ) from error
        return self


Replacements = Annotated[list[Replacement], Field(min_length=1, strict=True)]
