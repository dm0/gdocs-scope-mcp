"""Internal documents.snapshots responsibilities."""





def normalized(value):
    """Remove absolute indices without dropping native text or style data."""
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items()
                if k not in {'startIndex', 'endIndex'}}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value

