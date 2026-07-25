"""Safe, bounded DS9 Region parsing and serialization.

The module deliberately separates interchange from rendering.  Coordinates are
kept in their declared DS9 system; celestial coordinates and angular sizes are
normalized to degrees, while ``image``/``physical`` values remain in their DS9
pixel convention (normally 1-based).  This interchange layer intentionally
does not apply an image-origin or WCS transform.
No expression evaluation, callbacks, external resources, or DS9 command
properties are accepted.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Literal


CoordinateSystem = Literal["image", "physical", "fk5", "icrs"]
RegionShape = Literal["circle", "box", "ellipse", "polygon", "point"]
DiagnosticSeverity = Literal["warning", "error"]

SUPPORTED_COORDINATE_SYSTEMS = frozenset({"image", "physical", "fk5", "icrs"})
SUPPORTED_SHAPES = frozenset({"circle", "box", "ellipse", "polygon", "point"})

# Recognizing these declarations prevents an unsupported system from silently
# inheriting the preceding supported one.
_KNOWN_UNSUPPORTED_COORDINATE_SYSTEMS = frozenset(
    {
        "amplifier",
        "detector",
        "ecliptic",
        "galactic",
        "linear",
        "wcs",
        "wcs0",
        "wcsa",
        "wcsb",
        "wcsc",
        "wcsd",
        "wcse",
        "wcsf",
        "wcsg",
        "wcsh",
        "wcsi",
        "wcsj",
        "wcsk",
        "wcsl",
        "wcsm",
        "wcsn",
        "wcso",
        "wcsp",
        "wcsq",
        "wcsr",
        "wcss",
        "wcst",
        "wcsu",
        "wcsv",
        "wcsw",
        "wcsx",
        "wcsy",
        "wcsz",
    }
)

_SUPPORTED_ATTRIBUTES = frozenset(
    {
        "background",
        "color",
        "dash",
        "dashlist",
        "delete",
        "edit",
        "fixed",
        "font",
        "highlite",
        "include",
        "label",
        "move",
        "point",
        "select",
        "source",
        "tag",
        "text",
        "width",
    }
)
_FLAG_ATTRIBUTES = frozenset(
    {"background", "dash", "delete", "edit", "fixed", "highlite", "include", "move", "select", "source"}
)
_POINT_STYLES = frozenset({"arrow", "box", "boxcircle", "circle", "cross", "diamond", "x"})

_ATTRIBUTE_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_NUMBER_RE = re.compile(
    r"(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?P<unit>[dDrRiIpP'\"]?)"
)
_SEXAGESIMAL_RE = re.compile(
    r"(?P<sign>[+-]?)(?P<major>\d+):(?P<minute>\d+(?:\.\d*)?)"
    r"(?::(?P<second>\d+(?:\.\d*)?))?"
)
_COLOR_RE = re.compile(r"(?:#[0-9A-Fa-f]{3,8}|[A-Za-z][A-Za-z0-9_-]{0,31})")
_SAFE_BARE_ATTRIBUTE_RE = re.compile(r"[^\s{}'\"\\]+")
_UNSAFE_DIRECTIONAL_CONTROLS = frozenset(
    {
        "\u200e",  # left-to-right mark
        "\u200f",  # right-to-left mark
        "\u202a",  # directional embedding/override controls
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",  # directional isolate controls
        "\u2067",
        "\u2068",
        "\u2069",
    }
)


class DS9RegionError(ValueError):
    """Base class for DS9 interchange failures."""


class DS9RegionLimitError(DS9RegionError):
    """Raised when an input or output exceeds a configured safety budget."""


class DS9RegionSyntaxError(DS9RegionError):
    """Raised by strict parsing when one or more line errors were diagnosed."""

    def __init__(self, diagnostics: Sequence["DS9Diagnostic"]) -> None:
        self.diagnostics = tuple(diagnostics)
        first = next((item for item in self.diagnostics if item.severity == "error"), None)
        message = "Invalid DS9 Region input."
        if first is not None:
            message = f"Line {first.line}: {first.message}"
        super().__init__(message)


class DS9RegionIOError(DS9RegionError):
    """Raised for a safe file-I/O failure other than a missing path."""


@dataclass(frozen=True, slots=True)
class DS9RegionLimits:
    """Resource budgets applied before and during parsing/serialization."""

    max_input_bytes: int = 4 * 1024 * 1024
    max_lines: int = 50_000
    max_line_chars: int = 65_536
    max_regions: int = 10_000
    max_vertices_per_polygon: int = 4_096
    max_total_vertices: int = 100_000
    max_attributes_per_record: int = 64
    max_attribute_value_chars: int = 4_096
    max_diagnostics: int = 1_000
    max_numeric_token_chars: int = 128
    max_abs_pixel_value: float = 1.0e12

    def __post_init__(self) -> None:
        for name in (
            "max_input_bytes",
            "max_lines",
            "max_line_chars",
            "max_regions",
            "max_vertices_per_polygon",
            "max_total_vertices",
            "max_attributes_per_record",
            "max_attribute_value_chars",
            "max_diagnostics",
            "max_numeric_token_chars",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        if not math.isfinite(self.max_abs_pixel_value) or self.max_abs_pixel_value <= 0:
            raise ValueError("max_abs_pixel_value must be a positive finite number.")


DEFAULT_DS9_REGION_LIMITS = DS9RegionLimits()


@dataclass(frozen=True, slots=True)
class DS9Attribute:
    """One inert DS9 display attribute."""

    name: str
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise ValueError("DS9 attribute names must be strings.")
        normalized_name = self.name.strip().lower()
        if _ATTRIBUTE_NAME_RE.fullmatch(normalized_name) is None:
            raise ValueError(f"Invalid DS9 attribute name: {self.name!r}.")
        normalized_value = str(self.value)
        if _contains_unsafe_text(normalized_value, allow_layout_whitespace=False):
            raise ValueError(f"DS9 attribute {normalized_name!r} contains control characters.")
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "value", normalized_value)


@dataclass(frozen=True, slots=True)
class DS9Region:
    """One normalized DS9 shape.

    Celestial coordinates and angular sizes are degrees.  Image and physical
    coordinates/sizes retain DS9's normally 1-based pixel convention; a host
    converts them to its canvas origin.  Rotation angles are degrees in every
    system.
    """

    coordinate_system: CoordinateSystem
    shape: RegionShape
    parameters: tuple[float, ...]
    include: bool = True
    attributes: tuple[DS9Attribute, ...] = ()

    def __post_init__(self) -> None:
        system = str(self.coordinate_system).strip().lower()
        shape = str(self.shape).strip().lower()
        if system not in SUPPORTED_COORDINATE_SYSTEMS:
            raise ValueError(f"Unsupported DS9 coordinate system: {self.coordinate_system!r}.")
        if shape not in SUPPORTED_SHAPES:
            raise ValueError(f"Unsupported DS9 shape: {self.shape!r}.")
        if not isinstance(self.include, bool):
            raise ValueError("include must be a bool.")
        maximum_parameters = (
            2 * DEFAULT_DS9_REGION_LIMITS.max_vertices_per_polygon
            if shape == "polygon"
            else 5
        )
        raw_parameters = _bounded_tuple(
            self.parameters,
            maximum_parameters,
            "region parameters",
        )
        try:
            parameters = tuple(float(value) for value in raw_parameters)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("DS9 region parameters must be numeric.") from exc
        attributes = _bounded_tuple(
            self.attributes,
            DEFAULT_DS9_REGION_LIMITS.max_attributes_per_record,
            "region attributes",
        )
        if not all(isinstance(item, DS9Attribute) for item in attributes):
            raise ValueError("attributes must contain DS9Attribute objects.")
        _validate_normalized_geometry(system, shape, parameters, DEFAULT_DS9_REGION_LIMITS)
        object.__setattr__(self, "coordinate_system", system)
        object.__setattr__(self, "shape", shape)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "attributes", attributes)

    def attribute_values(self, name: str) -> tuple[str, ...]:
        """Return every value for an attribute (DS9 permits repeated tags)."""

        key = name.strip().lower()
        return tuple(item.value for item in self.attributes if item.name == key)

    @property
    def label(self) -> str | None:
        """Return the final ``text``/``label`` value, if any."""

        for item in reversed(self.attributes):
            if item.name in {"text", "label"}:
                return item.value
        return None

    @property
    def color(self) -> str | None:
        """Return the final local color override, if any."""

        values = self.attribute_values("color")
        return values[-1] if values else None


@dataclass(frozen=True, slots=True)
class DS9Diagnostic:
    """A bounded, line-oriented parser diagnostic."""

    line: int
    severity: DiagnosticSeverity
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class DS9RegionDocument:
    """Parsed DS9 regions, global display attributes, and diagnostics."""

    regions: tuple[DS9Region, ...] = ()
    global_attributes: tuple[DS9Attribute, ...] = ()
    diagnostics: tuple[DS9Diagnostic, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(item.severity == "error" for item in self.diagnostics)

    def effective_attributes(self, region: DS9Region) -> tuple[DS9Attribute, ...]:
        """Return global attributes followed by region-local overrides."""

        return self.global_attributes + region.attributes


@dataclass(slots=True)
class _ParserState:
    limits: DS9RegionLimits
    diagnostics: list[DS9Diagnostic] = field(default_factory=list)

    def diagnose(self, line: int, severity: DiagnosticSeverity, code: str, message: str) -> None:
        if len(self.diagnostics) >= self.limits.max_diagnostics:
            raise DS9RegionLimitError(
                f"DS9 input produced more than {self.limits.max_diagnostics:,} diagnostics."
            )
        self.diagnostics.append(DS9Diagnostic(line, severity, code, message))


class _ShapeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def parse_ds9_regions(
    source: str | bytes,
    *,
    strict: bool = False,
    limits: DS9RegionLimits = DEFAULT_DS9_REGION_LIMITS,
) -> DS9RegionDocument:
    """Parse bounded DS9 Region text.

    Malformed or unsupported individual records are skipped with diagnostics so
    callers can present partial imports.  Structural/resource-limit violations
    are rejected with :class:`DS9RegionLimitError`.  Set ``strict=True`` to
    raise :class:`DS9RegionSyntaxError` when any line-level error is present.
    """

    text = _decode_source(source, limits)
    lines = text.splitlines()
    if len(lines) > limits.max_lines:
        raise DS9RegionLimitError(
            f"DS9 input has {len(lines):,} lines; limit is {limits.max_lines:,}."
        )

    state = _ParserState(limits)
    regions: list[DS9Region] = []
    global_attributes: tuple[DS9Attribute, ...] = ()
    current_system: str | None = "physical"
    total_vertices = 0

    for line_number, raw_line in enumerate(lines, start=1):
        if len(raw_line) > limits.max_line_chars:
            raise DS9RegionLimitError(
                f"Line {line_number} has {len(raw_line):,} characters; "
                f"limit is {limits.max_line_chars:,}."
            )
        code, comment = _split_comment(raw_line)
        code = code.strip()
        if not code:
            continue

        if code.lower() == "global" or code.lower().startswith("global "):
            payload = code[6:].strip()
            global_attributes = _parse_attributes(payload, line_number, state)
            continue

        statements = [item.strip() for item in _split_outside(code, ";") if item.strip()]
        if not statements:
            continue
        attribute_target = max(
            (index for index, item in enumerate(statements) if "(" in item),
            default=-1,
        )
        local_attributes = (
            _parse_attributes(comment.strip(), line_number, state) if comment.strip() else ()
        )

        for statement_index, statement in enumerate(statements):
            lowered = statement.lower()
            if lowered in SUPPORTED_COORDINATE_SYSTEMS:
                current_system = lowered
                continue
            if lowered in _KNOWN_UNSUPPORTED_COORDINATE_SYSTEMS:
                current_system = None
                state.diagnose(
                    line_number,
                    "warning",
                    "unsupported-coordinate-system",
                    f"Coordinate system {statement!r} is not supported and following shapes are skipped.",
                )
                continue
            if "(" not in statement:
                state.diagnose(
                    line_number,
                    "error",
                    "invalid-statement",
                    f"Expected a coordinate declaration or shape, got {statement!r}.",
                )
                # A bare identifier is most likely an unsupported coordinate
                # declaration.  Clearing the state prevents following shapes
                # from being silently interpreted in the previous system.
                current_system = None
                continue
            if current_system is None:
                state.diagnose(
                    line_number,
                    "warning",
                    "shape-in-unsupported-system",
                    "Shape skipped because its active coordinate system is unsupported.",
                )
                continue

            attributes = local_attributes if statement_index == attribute_target else ()
            try:
                region = _parse_shape(statement, current_system, attributes, limits)
            except _ShapeError as exc:
                severity: DiagnosticSeverity = (
                    "warning" if exc.code == "unsupported-shape" else "error"
                )
                state.diagnose(line_number, severity, exc.code, str(exc))
                continue

            if len(regions) >= limits.max_regions:
                raise DS9RegionLimitError(
                    f"DS9 input contains more than {limits.max_regions:,} regions."
                )
            if region.shape == "polygon":
                vertices = len(region.parameters) // 2
                total_vertices += vertices
                if total_vertices > limits.max_total_vertices:
                    raise DS9RegionLimitError(
                        "DS9 polygons exceed the total vertex limit of "
                        f"{limits.max_total_vertices:,}."
                    )
            regions.append(region)

    document = DS9RegionDocument(
        regions=tuple(regions),
        global_attributes=global_attributes,
        diagnostics=tuple(state.diagnostics),
    )
    if strict and document.has_errors:
        raise DS9RegionSyntaxError(document.diagnostics)
    return document


def serialize_ds9_regions(
    source: DS9RegionDocument | Iterable[DS9Region],
    *,
    global_attributes: Iterable[DS9Attribute] | None = None,
    limits: DS9RegionLimits = DEFAULT_DS9_REGION_LIMITS,
) -> str:
    """Serialize regions to a canonical DS9 4.1 document."""

    if isinstance(source, DS9RegionDocument):
        regions = _bounded_tuple(source.regions, limits.max_regions, "regions")
        globals_to_write = (
            _bounded_tuple(
                source.global_attributes,
                limits.max_attributes_per_record,
                "global attributes",
            )
            if global_attributes is None
            else _bounded_tuple(
                global_attributes,
                limits.max_attributes_per_record,
                "global attributes",
            )
        )
    else:
        regions = _bounded_tuple(source, limits.max_regions, "regions")
        globals_to_write = _bounded_tuple(
            global_attributes or (),
            limits.max_attributes_per_record,
            "global attributes",
        )

    if len(regions) > limits.max_regions:
        raise DS9RegionLimitError(
            f"Cannot write {len(regions):,} regions; limit is {limits.max_regions:,}."
        )
    _validate_attribute_collection(globals_to_write, limits)

    lines: list[str] = []
    output_size = 0

    def append_line(line: str) -> None:
        nonlocal output_size
        if len(line) > limits.max_line_chars:
            raise DS9RegionLimitError(
                f"Serialized region line exceeds {limits.max_line_chars:,} characters."
            )
        line_size = len(line.encode("utf-8")) + 1
        if output_size + line_size > limits.max_input_bytes:
            raise DS9RegionLimitError(
                "Serialized DS9 output exceeds the "
                f"{limits.max_input_bytes:,}-byte limit."
            )
        lines.append(line)
        output_size += line_size

    append_line("# Region file format: DS9 version 4.1")
    if globals_to_write:
        append_line("global " + _serialize_attributes(globals_to_write, limits))

    active_system: str | None = None
    total_vertices = 0
    for region in regions:
        if not isinstance(region, DS9Region):
            raise TypeError("serialize_ds9_regions expects DS9Region objects.")
        _validate_normalized_geometry(
            region.coordinate_system,
            region.shape,
            region.parameters,
            limits,
        )
        _validate_attribute_collection(region.attributes, limits)
        if region.shape == "polygon":
            total_vertices += len(region.parameters) // 2
            if total_vertices > limits.max_total_vertices:
                raise DS9RegionLimitError(
                    "DS9 polygons exceed the total vertex limit of "
                    f"{limits.max_total_vertices:,}."
                )
        if active_system != region.coordinate_system:
            active_system = region.coordinate_system
            append_line(active_system)

        prefix = "" if region.include else "-"
        arguments = _serialize_parameters(region)
        line = f"{prefix}{region.shape}({arguments})"
        if region.attributes:
            line += " # " + _serialize_attributes(region.attributes, limits)
        append_line(line)

    output = "\n".join(lines) + "\n"
    return output


def read_ds9_region_file(
    path: str | os.PathLike[str],
    *,
    strict: bool = False,
    limits: DS9RegionLimits = DEFAULT_DS9_REGION_LIMITS,
) -> DS9RegionDocument:
    """Read a regular local region file without following a second path lookup."""

    with _open_regular_input(path) as stream:
        source_stat = os.fstat(stream.fileno())
        if source_stat.st_size > limits.max_input_bytes:
            raise DS9RegionLimitError(
                f"DS9 file is {source_stat.st_size:,} bytes; limit is {limits.max_input_bytes:,}."
            )
        payload = stream.read(limits.max_input_bytes + 1)
    if len(payload) > limits.max_input_bytes:
        raise DS9RegionLimitError(
            f"DS9 file exceeds the {limits.max_input_bytes:,}-byte limit."
        )
    return parse_ds9_regions(payload, strict=strict, limits=limits)


def write_ds9_region_file(
    path: str | os.PathLike[str],
    source: DS9RegionDocument | Iterable[DS9Region],
    *,
    global_attributes: Iterable[DS9Attribute] | None = None,
    overwrite: bool = False,
    limits: DS9RegionLimits = DEFAULT_DS9_REGION_LIMITS,
) -> None:
    """Write a DS9 document, using atomic replacement when overwrite is allowed."""

    output = serialize_ds9_regions(
        source,
        global_attributes=global_attributes,
        limits=limits,
    ).encode("utf-8")
    target = Path(path)
    if not overwrite:
        with target.open("xb") as stream:
            stream.write(output)
        return

    parent = target.parent
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@contextmanager
def _open_regular_input(path: str | os.PathLike[str]) -> Iterator[object]:
    """Open a nonblocking stable handle, then reject non-regular inputs."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise DS9RegionIOError(f"Could not open DS9 Region input {str(path)!r}: {exc}") from exc
    try:
        source_stat = os.fstat(descriptor)
        if not stat.S_ISREG(source_stat.st_mode):
            raise DS9RegionIOError(f"DS9 Region input must be a regular local file: {str(path)!r}.")
        stream = os.fdopen(descriptor, "rb", buffering=0)
    except Exception:
        os.close(descriptor)
        raise
    try:
        yield stream
    finally:
        stream.close()


def _decode_source(source: str | bytes, limits: DS9RegionLimits) -> str:
    if isinstance(source, bytes):
        if len(source) > limits.max_input_bytes:
            raise DS9RegionLimitError(
                f"DS9 input is {len(source):,} bytes; limit is {limits.max_input_bytes:,}."
            )
        try:
            text = source.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise DS9RegionError(f"DS9 input is not valid UTF-8: {exc}") from exc
    else:
        if not isinstance(source, str):
            raise TypeError("DS9 source must be str or bytes.")
        if len(source) > limits.max_input_bytes:
            raise DS9RegionLimitError(
                f"DS9 input has {len(source):,} characters; byte limit is {limits.max_input_bytes:,}."
            )
        text = source.lstrip("\ufeff")
        try:
            encoded_size = len(source.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise DS9RegionError("DS9 input contains invalid Unicode text.") from exc
        if encoded_size > limits.max_input_bytes:
            raise DS9RegionLimitError(
                f"DS9 input is {encoded_size:,} bytes; limit is {limits.max_input_bytes:,}."
            )
    if _contains_unsafe_text(text, allow_layout_whitespace=True):
        raise DS9RegionError("DS9 input contains unsafe control characters.")
    return text


def _contains_unsafe_text(value: str, *, allow_layout_whitespace: bool) -> bool:
    allowed = {"\t", "\r", "\n"} if allow_layout_whitespace else set()
    return any(
        (char not in allowed and (ord(char) < 32 or ord(char) == 127))
        or 0xD800 <= ord(char) <= 0xDFFF
        or char in _UNSAFE_DIRECTIONAL_CONTROLS
        for char in value
    )


def _bounded_tuple(source: Iterable[object], maximum: int, label: str) -> tuple:
    """Consume at most ``maximum + 1`` items from a possibly lazy iterable."""

    result: list[object] = []
    for item in source:
        if len(result) >= maximum:
            raise DS9RegionLimitError(
                f"Cannot write more than {maximum:,} {label}."
            )
        result.append(item)
    return tuple(result)


def _split_comment(line: str) -> tuple[str, str]:
    brace_depth = 0
    paren_depth = 0
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        # Quotes inside geometry parentheses are DS9 angular unit suffixes,
        # not string delimiters (for example a 30-arcsecond circle uses 30").
        if char in {"'", '"'} and paren_depth == 0:
            quote = char
            continue
        if char == "{":
            brace_depth += 1
            continue
        if char == "}" and brace_depth:
            brace_depth -= 1
            continue
        if char == "(" and brace_depth == 0:
            paren_depth += 1
            continue
        if char == ")" and brace_depth == 0 and paren_depth:
            paren_depth -= 1
            continue
        # Do not mistake an unquoted hexadecimal color value for a comment.
        if char == "#" and brace_depth == 0 and paren_depth == 0:
            before = line[:index].rstrip()
            if before.endswith("="):
                continue
            return line[:index], line[index + 1 :]
    return line, ""


def _split_outside(text: str, separator: str) -> list[str]:
    result: list[str] = []
    start = 0
    brace_depth = 0
    paren_depth = 0
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'} and paren_depth == 0:
            quote = char
        elif char == "{":
            brace_depth += 1
        elif char == "}" and brace_depth:
            brace_depth -= 1
        elif char == "(":
            paren_depth += 1
        elif char == ")" and paren_depth:
            paren_depth -= 1
        elif char == separator and brace_depth == 0 and paren_depth == 0:
            result.append(text[start:index])
            start = index + 1
    result.append(text[start:])
    return result


def _parse_attributes(text: str, line: int, state: _ParserState) -> tuple[DS9Attribute, ...]:
    if not text or "=" not in text:
        return ()
    result: list[DS9Attribute] = []
    index = 0
    encountered = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        match = _ATTRIBUTE_NAME_RE.match(text, index)
        if match is None:
            state.diagnose(line, "warning", "invalid-attribute", "Ignored malformed DS9 attribute text.")
            index = _skip_token(text, index)
            continue
        name = match.group(0).lower()
        index = match.end()
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] != "=":
            state.diagnose(
                line,
                "warning",
                "invalid-attribute",
                f"Ignored attribute {name!r} without '='.",
            )
            index = _skip_token(text, index)
            continue
        index += 1
        while index < len(text) and text[index].isspace():
            index += 1
        try:
            value, index = _consume_attribute_value(text, index)
        except _ShapeError as exc:
            state.diagnose(line, "warning", exc.code, str(exc))
            break

        encountered += 1
        if encountered > state.limits.max_attributes_per_record:
            raise DS9RegionLimitError(
                f"Line {line} has more than {state.limits.max_attributes_per_record:,} attributes."
            )

        if name in {"dashlist", "point"}:
            probe = index
            while probe < len(text) and text[probe].isspace():
                probe += 1
            extra_end = _skip_token(text, probe)
            extra = text[probe:extra_end]
            accepts_extra = (
                name == "dashlist" and _NUMBER_RE.fullmatch(extra) is not None
            ) or (
                name == "point" and extra.isdecimal()
            )
            if extra and "=" not in extra and accepts_extra:
                value = f"{value} {extra}"
                index = extra_end

        try:
            normalized = _validated_attribute_value(name, value, state.limits)
        except _ShapeError as exc:
            state.diagnose(line, "warning", exc.code, str(exc))
            continue
        result.append(DS9Attribute(name, normalized))
    return tuple(result)


def _consume_attribute_value(text: str, index: int) -> tuple[str, int]:
    if index >= len(text):
        return "", index
    opener = text[index]
    if opener not in {"{", "'", '"'}:
        end = _skip_token(text, index)
        return text[index:end], end
    closer = "}" if opener == "{" else opener
    depth = 1
    index += 1
    output: list[str] = []
    escaped = False
    while index < len(text):
        char = text[index]
        index += 1
        if escaped:
            output.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if opener == "{" and char == "{":
            depth += 1
            output.append(char)
            continue
        if char == closer:
            depth -= 1
            if depth == 0:
                return "".join(output), index
            output.append(char)
            continue
        output.append(char)
    raise _ShapeError("unterminated-attribute", "Ignored unterminated quoted/braced attribute.")


def _skip_token(text: str, index: int) -> int:
    while index < len(text) and not text[index].isspace():
        index += 1
    return index


def _validated_attribute_value(name: str, value: str, limits: DS9RegionLimits) -> str:
    if name not in _SUPPORTED_ATTRIBUTES:
        raise _ShapeError("unsupported-attribute", f"Ignored unsupported attribute {name!r}.")
    if len(value) > limits.max_attribute_value_chars:
        raise DS9RegionLimitError(
            f"Attribute {name!r} exceeds {limits.max_attribute_value_chars:,} characters."
        )
    if _contains_unsafe_text(value, allow_layout_whitespace=False):
        raise _ShapeError("unsafe-attribute", f"Ignored attribute {name!r} containing control characters.")
    if name == "color" and _COLOR_RE.fullmatch(value) is None:
        raise _ShapeError("invalid-color", f"Ignored invalid color {value!r}.")
    if name in _FLAG_ATTRIBUTES and value not in {"0", "1"}:
        raise _ShapeError("invalid-flag", f"Ignored {name!r}; expected 0 or 1.")
    if name == "width":
        try:
            width = int(value)
        except ValueError as exc:
            raise _ShapeError("invalid-width", "Ignored non-integer width attribute.") from exc
        if not 1 <= width <= 1_000:
            raise _ShapeError("invalid-width", "Ignored width outside 1..1000.")
    if name == "dashlist":
        parts = value.split()
        if len(parts) != 2:
            raise _ShapeError("invalid-dashlist", "Ignored dashlist; expected two positive numbers.")
        try:
            dash_values = tuple(float(part) for part in parts)
        except ValueError as exc:
            raise _ShapeError("invalid-dashlist", "Ignored non-numeric dashlist.") from exc
        if any(not math.isfinite(part) or part <= 0 or part > 1.0e6 for part in dash_values):
            raise _ShapeError("invalid-dashlist", "Ignored unsafe dashlist values.")
    if name == "point":
        parts = value.lower().split()
        if not parts or parts[0] not in _POINT_STYLES or len(parts) > 2:
            raise _ShapeError("invalid-point-style", f"Ignored invalid point style {value!r}.")
        if len(parts) == 2:
            try:
                size = int(parts[1])
            except ValueError as exc:
                raise _ShapeError("invalid-point-style", "Ignored non-integer point size.") from exc
            if not 1 <= size <= 1_000:
                raise _ShapeError("invalid-point-style", "Ignored point size outside 1..1000.")
    return value


def _parse_shape(
    statement: str,
    coordinate_system: str,
    attributes: tuple[DS9Attribute, ...],
    limits: DS9RegionLimits,
) -> DS9Region:
    match = re.fullmatch(
        r"\s*(?P<prefix>[+-]?)(?P<shape>[A-Za-z]+)\s*\((?P<arguments>.*)\)\s*",
        statement,
    )
    if match is None:
        raise _ShapeError("invalid-shape-syntax", f"Malformed DS9 shape: {statement!r}.")
    shape = match.group("shape").lower()
    if shape not in SUPPORTED_SHAPES:
        raise _ShapeError("unsupported-shape", f"Shape {shape!r} is not supported and was skipped.")
    tokens = [item.strip() for item in match.group("arguments").split(",")]
    if any(not item for item in tokens):
        raise _ShapeError("invalid-arity", f"Shape {shape!r} contains an empty argument.")
    _validate_shape_arity(shape, len(tokens), limits)

    values: list[float] = []
    for index, token in enumerate(tokens):
        role = _parameter_role(shape, index, len(tokens))
        if role == "x":
            value = _parse_position(token, coordinate_system, is_ra=True, limits=limits)
        elif role == "y":
            value = _parse_position(token, coordinate_system, is_ra=False, limits=limits)
        elif role == "size":
            value = _parse_size(token, coordinate_system, limits)
        else:
            value = _parse_angle(token, limits)
        values.append(value)

    include = match.group("prefix") != "-"
    return DS9Region(
        coordinate_system=coordinate_system,
        shape=shape,
        parameters=tuple(values),
        include=include,
        attributes=attributes,
    )


def _validate_shape_arity(shape: str, count: int, limits: DS9RegionLimits) -> None:
    valid = {
        "circle": count == 3,
        "point": count == 2,
        "box": count in {4, 5},
        "ellipse": count in {4, 5},
        "polygon": count >= 6 and count % 2 == 0,
    }[shape]
    if not valid:
        raise _ShapeError("invalid-arity", f"Shape {shape!r} has an invalid argument count ({count}).")
    if shape == "polygon" and count // 2 > limits.max_vertices_per_polygon:
        raise DS9RegionLimitError(
            f"Polygon has {count // 2:,} vertices; limit is {limits.max_vertices_per_polygon:,}."
        )


def _parameter_role(shape: str, index: int, count: int) -> str:
    if shape in {"point", "circle", "box", "ellipse"} and index < 2:
        return "x" if index == 0 else "y"
    if shape == "polygon":
        return "x" if index % 2 == 0 else "y"
    if shape == "circle":
        return "size"
    if shape in {"box", "ellipse"} and index in {2, 3}:
        return "size"
    if shape in {"box", "ellipse"} and count == 5 and index == 4:
        return "angle"
    raise AssertionError(f"Unexpected {shape} parameter {index}.")


def _parse_position(
    token: str,
    coordinate_system: str,
    *,
    is_ra: bool,
    limits: DS9RegionLimits,
) -> float:
    _check_numeric_token_length(token, limits)
    if coordinate_system in {"fk5", "icrs"} and ":" in token:
        return _parse_sexagesimal(token, is_ra=is_ra)
    number, unit = _parse_number(token)
    if coordinate_system in {"fk5", "icrs"}:
        if unit == "r":
            number = math.degrees(number)
        elif unit not in {"", "d"}:
            raise _ShapeError("invalid-unit", f"Invalid celestial position unit in {token!r}.")
        if is_ra:
            if number == 360.0:
                return 0.0
            if not 0.0 <= number < 360.0:
                raise _ShapeError("coordinate-out-of-range", f"RA {number!r} is outside [0, 360).")
        elif not -90.0 <= number <= 90.0:
            raise _ShapeError("coordinate-out-of-range", f"Declination {number!r} is outside [-90, 90].")
    else:
        if unit not in {"", "i", "p"}:
            raise _ShapeError("invalid-unit", f"Invalid pixel coordinate unit in {token!r}.")
        if abs(number) > limits.max_abs_pixel_value:
            raise _ShapeError("coordinate-out-of-range", f"Pixel coordinate {number!r} is too large.")
    return number


def _parse_size(token: str, coordinate_system: str, limits: DS9RegionLimits) -> float:
    _check_numeric_token_length(token, limits)
    number, unit = _parse_number(token)
    if coordinate_system in {"fk5", "icrs"}:
        factors = {"": 1.0, "d": 1.0, "r": 180.0 / math.pi, "'": 1.0 / 60.0, '"': 1.0 / 3600.0}
        if unit not in factors:
            raise _ShapeError("invalid-unit", f"Invalid angular size unit in {token!r}.")
        number *= factors[unit]
        if number > 360.0:
            raise _ShapeError("size-out-of-range", f"Angular size {number!r} degrees is too large.")
    else:
        if unit not in {"", "i", "p"}:
            raise _ShapeError("invalid-unit", f"Invalid pixel size unit in {token!r}.")
        if number > limits.max_abs_pixel_value:
            raise _ShapeError("size-out-of-range", f"Pixel size {number!r} is too large.")
    if number <= 0:
        raise _ShapeError("size-out-of-range", "Region sizes must be greater than zero.")
    return number


def _parse_angle(token: str, limits: DS9RegionLimits) -> float:
    _check_numeric_token_length(token, limits)
    number, unit = _parse_number(token)
    if unit == "r":
        number = math.degrees(number)
    elif unit not in {"", "d"}:
        raise _ShapeError("invalid-unit", f"Invalid angle unit in {token!r}.")
    if abs(number) > limits.max_abs_pixel_value:
        raise _ShapeError("angle-out-of-range", f"Angle {number!r} is too large.")
    return number


def _parse_number(token: str) -> tuple[float, str]:
    match = _NUMBER_RE.fullmatch(token)
    if match is None:
        raise _ShapeError("invalid-number", f"Invalid numeric token {token!r}.")
    number = float(match.group("number"))
    if not math.isfinite(number):
        raise _ShapeError("non-finite-number", f"Non-finite numeric token {token!r} is not allowed.")
    return number, match.group("unit").lower()


def _parse_sexagesimal(token: str, *, is_ra: bool) -> float:
    match = _SEXAGESIMAL_RE.fullmatch(token)
    if match is None:
        raise _ShapeError("invalid-sexagesimal", f"Invalid sexagesimal coordinate {token!r}.")
    sign_text = match.group("sign")
    major = int(match.group("major"))
    minute = float(match.group("minute"))
    second = float(match.group("second") or 0.0)
    if minute >= 60.0 or second >= 60.0:
        raise _ShapeError("invalid-sexagesimal", f"Invalid sexagesimal coordinate {token!r}.")
    if is_ra:
        if sign_text == "-" or major > 24 or (major == 24 and (minute or second)):
            raise _ShapeError("coordinate-out-of-range", f"RA {token!r} is outside 0h..24h.")
        degrees = (major + minute / 60.0 + second / 3600.0) * 15.0
        return 0.0 if degrees == 360.0 else degrees
    if major > 90 or (major == 90 and (minute or second)):
        raise _ShapeError("coordinate-out-of-range", f"Declination {token!r} is outside -90..90 degrees.")
    value = major + minute / 60.0 + second / 3600.0
    return -value if sign_text == "-" else value


def _check_numeric_token_length(token: str, limits: DS9RegionLimits) -> None:
    if len(token) > limits.max_numeric_token_chars:
        raise DS9RegionLimitError(
            f"Numeric token exceeds {limits.max_numeric_token_chars:,} characters."
        )


def _validate_normalized_geometry(
    coordinate_system: str,
    shape: str,
    parameters: Sequence[float],
    limits: DS9RegionLimits,
) -> None:
    _validate_shape_arity(shape, len(parameters), limits)
    if any(not math.isfinite(value) for value in parameters):
        raise ValueError("DS9 region parameters must be finite.")
    for index, value in enumerate(parameters):
        role = _parameter_role(shape, index, len(parameters))
        if role == "size" and value <= 0:
            raise ValueError("DS9 region sizes must be greater than zero.")
        if role == "angle" and abs(value) > limits.max_abs_pixel_value:
            raise ValueError("DS9 region angle exceeds the configured numeric range.")
        if coordinate_system in {"fk5", "icrs"}:
            if role == "x" and not 0.0 <= value < 360.0:
                raise ValueError("Celestial longitude must be in [0, 360).")
            if role == "y" and not -90.0 <= value <= 90.0:
                raise ValueError("Celestial latitude must be in [-90, 90].")
            if role == "size" and value > 360.0:
                raise ValueError("Celestial sizes cannot exceed 360 degrees.")
        elif role in {"x", "y", "size"} and abs(value) > limits.max_abs_pixel_value:
            raise ValueError("DS9 pixel geometry exceeds the configured numeric range.")


def _serialize_parameters(region: DS9Region) -> str:
    values: list[str] = []
    for index, value in enumerate(region.parameters):
        role = _parameter_role(region.shape, index, len(region.parameters))
        encoded = _format_float(value)
        if region.coordinate_system in {"fk5", "icrs"} and role == "size":
            encoded += "d"
        values.append(encoded)
    return ",".join(values)


def _format_float(value: float) -> str:
    result = format(float(value), ".17g")
    return "0" if result in {"-0", "-0.0"} else result


def _validate_attribute_collection(
    attributes: Sequence[DS9Attribute],
    limits: DS9RegionLimits,
) -> None:
    if len(attributes) > limits.max_attributes_per_record:
        raise DS9RegionLimitError(
            f"Attribute count exceeds {limits.max_attributes_per_record:,}."
        )
    for item in attributes:
        if not isinstance(item, DS9Attribute):
            raise TypeError("DS9 attributes must be DS9Attribute objects.")
        try:
            _validated_attribute_value(item.name, item.value, limits)
        except _ShapeError as exc:
            raise DS9RegionError(str(exc)) from exc


def _serialize_attributes(attributes: Sequence[DS9Attribute], limits: DS9RegionLimits) -> str:
    _validate_attribute_collection(attributes, limits)
    return " ".join(f"{item.name}={_quote_attribute_value(item)}" for item in attributes)


def _quote_attribute_value(attribute: DS9Attribute) -> str:
    value = attribute.value
    if attribute.name not in {"font", "label", "tag", "text"} and _SAFE_BARE_ATTRIBUTE_RE.fullmatch(value):
        return value
    escaped = value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    return "{" + escaped + "}"


__all__ = [
    "CoordinateSystem",
    "DEFAULT_DS9_REGION_LIMITS",
    "DS9Attribute",
    "DS9Diagnostic",
    "DS9Region",
    "DS9RegionDocument",
    "DS9RegionError",
    "DS9RegionIOError",
    "DS9RegionLimitError",
    "DS9RegionLimits",
    "DS9RegionSyntaxError",
    "DiagnosticSeverity",
    "RegionShape",
    "SUPPORTED_COORDINATE_SYSTEMS",
    "SUPPORTED_SHAPES",
    "parse_ds9_regions",
    "read_ds9_region_file",
    "serialize_ds9_regions",
    "write_ds9_region_file",
]
