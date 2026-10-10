"""Zinc reader for FIN point/equipment grids; compound cells remain opaque.

This is deliberately not a general-purpose Haystack expression interpreter.
"""
from dataclasses import dataclass
import json
import math
import re


@dataclass(frozen=True)
class Ref:
    id: str
    display: str = ""


@dataclass(frozen=True)
class Number:
    value: float
    unit: str = ""


class ZincError(ValueError):
    """Malformed or server error grid."""


MARKER = object()
NUMBER = re.compile(r"(-?(?:[0-9_]+(?:\.[0-9_]+)?)(?:[eE][+-]?[0-9]+)?)((?:[^\W\d]|[%/°Δ²³$µ])*)$")
REFERENCE = re.compile(r"[A-Za-z0-9_:~.\-]+$")


def quote(value):
    return json.dumps(value, ensure_ascii=False).replace("$", "\\$")


def unquote(value):
    # Zinc permits \$ in addition to JSON's string escapes.
    return json.loads(value.replace("\\$", "$"))


def split_top_level(text, separator):
    result, start, stack = [], 0, []
    quoted, escaped, i = None, False, 0
    while i < len(text):
        char = text[i]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quoted:
                quoted = None
        elif char in ('"', '`'):
            quoted = char
        elif text[i:i + 2] == "<<":
            stack.append("<<")
            i += 1
        elif text[i:i + 2] == ">>":
            if not stack or stack.pop() != "<<":
                raise ZincError("Unbalanced nested grid")
            i += 1
        elif char in "[{(":
            stack.append(char)
        elif char in "]})":
            expected = {"]": "[", "}": "{", ")": "("}[char]
            if not stack or stack.pop() != expected:
                raise ZincError("Unbalanced compound cell")
        elif char == separator and not stack:
            result.append(text[start:i].strip())
            start = i + 1
        i += 1
    if quoted or stack:
        raise ZincError("Incomplete row")
    return result + [text[start:].strip()]


def split_cells(line):
    return split_top_level(line, ",")


def scalar(token):
    if token in ("", "N", "NA", "NaN", "INF", "-INF"):
        return None
    if token == "M":
        return MARKER
    if token in ("T", "F"):
        return token == "T"
    if token.startswith('"'):
        return unquote(token)
    if token.startswith("@"):
        ident, _, label = token[1:].partition(" ")
        if not REFERENCE.fullmatch(ident):
            raise ZincError("Invalid reference")
        return Ref(ident, unquote(label) if label else "")
    match = NUMBER.fullmatch(token)
    if match:
        number = float(match[1].replace("_", ""))
        return Number(number, match[2]) if math.isfinite(number) else None
    # Dates, times, URI, dict, list and other metadata are not numeric values.
    return token


def parse_grids(text):
    grids, rows, columns = [], None, None
    for line in split_top_level(text.strip(), "\n"):
        if not line:
            continue
        if line.startswith('ver:"3.0"'):
            if re.search(r"(?:^|\s)err(?:\s|$|:)", line):
                raise ZincError("FIN returned an error grid")
            rows, columns = [], None
            grids.append(rows)
        elif rows is None:
            raise ZincError("Expected Zinc 3.0 grid")
        elif columns is None:
            columns = [cell.split(" ", 1)[0] for cell in split_cells(line)]
        else:
            cells = split_cells(line)
            if len(cells) != len(columns):
                raise ZincError("Unexpected column count")
            rows.append(dict(zip(columns, map(scalar, cells))))
    if not grids or columns is None:
        raise ZincError("Incomplete Zinc grid")
    return grids


def value(raw):
    return raw.value if isinstance(raw, Number) else raw


def reference(raw):
    return raw.id if isinstance(raw, Ref) else None
