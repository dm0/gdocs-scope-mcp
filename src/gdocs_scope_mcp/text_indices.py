"""Convert Python text lengths to Google Docs UTF-16 index units."""



def utf16_length(text: str) -> int:
    """Return the number of UTF-16 code units in Unicode text."""
    return len(text.encode('utf-16-le')) // 2
