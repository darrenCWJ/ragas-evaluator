"""Shared log sanitisation (importable from app/, pipeline/, evaluation/).

User-influenced values (names, questions, emails, model ids, exception
messages wrapping user input) must not be able to forge extra log lines.
clean() flattens CR/LF before the value reaches a logger call
(CodeQL py/log-injection).
"""


def clean(value) -> str:
    """Render a value for logging with newlines escaped."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")
