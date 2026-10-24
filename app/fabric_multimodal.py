"""Bounded document and PNG pixel measurements, without inference or downloads.

The PNG decoder deliberately accepts only non-interlaced 8-bit RGB/RGBA PNGs.
Every chunk CRC and the complete bounded zlib stream are validated before pixels
are measured. This is visual measurement, not object detection, OCR, image
reasoning, speech recognition, physical automation or confidential computing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import struct
import zlib


MAX_IMAGE_BYTES = 524_288
MAX_IMAGE_PIXELS = 262_144
MAX_IMAGE_SIDE = 2048
MAX_BASE64_CHARS = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_IMAGE_INPUT = {
    "type": "object",
    "required": ["image_base64"],
    "additionalProperties": False,
    "properties": {"image_base64": {"type": "string", "minLength": 1, "maxLength": MAX_BASE64_CHARS}},
}
_IMAGE_OUTPUT = {
    "type": "object",
    "required": ["execution_mode", "source_sha256", "format", "width", "height", "pixel_count", "channels", "scope"],
    "properties": {
        "execution_mode": {"type": "string", "enum": ["DETERMINISTIC"]},
        "source_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "format": {"type": "string", "enum": ["PNG"]},
        "width": {"type": "integer", "minimum": 1, "maximum": MAX_IMAGE_SIDE},
        "height": {"type": "integer", "minimum": 1, "maximum": MAX_IMAGE_SIDE},
        "pixel_count": {"type": "integer", "minimum": 1, "maximum": MAX_IMAGE_PIXELS},
        "channels": {"type": "integer", "enum": [3, 4]},
        "scope": {"type": "string"},
    },
}

CONTRACTS = {
    "f17": {
        "version": "0.3.0",
        "operations": [
            {
                "operation": "image.inspect",
                "input_schema": _IMAGE_INPUT,
                "output_schema": _IMAGE_OUTPUT,
                "scope": "VALIDATED_PNG_STRUCTURE_AND_DIMENSIONS_ONLY",
            },
            {
                "operation": "document.inspect",
                "input_schema": {
                    "type": "object",
                    "required": ["text"],
                    "additionalProperties": False,
                    "properties": {"text": {"type": "string", "maxLength": 16000}},
                },
                "output_schema": {
                    "type": "object",
                    "required": [
                        "execution_mode",
                        "source_sha256",
                        "characters",
                        "utf8_bytes",
                        "lines",
                        "words",
                        "scope",
                    ],
                    "properties": {
                        "execution_mode": {"type": "string", "enum": ["DETERMINISTIC"]},
                        "source_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                        "characters": {"type": "integer", "minimum": 0, "maximum": 16000},
                        "utf8_bytes": {"type": "integer", "minimum": 0, "maximum": 64000},
                        "lines": {"type": "integer", "minimum": 0},
                        "words": {"type": "integer", "minimum": 0},
                        "scope": {"type": "string"},
                    },
                },
                "scope": "SUBMITTED_UNICODE_TEXT_STRUCTURE_ONLY",
            },
        ],
        "limitations": [
            "PNG: 8-bit RGB/RGBA, non-interlaced, at most 262144 pixels and 524288 encoded file bytes.",
            "Text inspection measures submitted text; no PDF extraction or semantic content analysis.",
            "No model inference, audio/video analysis, OCR or image reasoning is performed.",
        ],
    },
    "f32": {
        "version": "0.3.0",
        "operations": [
            {
                "operation": "image.measure",
                "input_schema": _IMAGE_INPUT,
                "output_schema": {
                    **_IMAGE_OUTPUT,
                    "required": [*_IMAGE_OUTPUT["required"], "channel_statistics", "opaque_fraction"],
                    "properties": {
                        **_IMAGE_OUTPUT["properties"],
                        "channel_statistics": {"type": "array", "minItems": 3, "maxItems": 4},
                        "opaque_fraction": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
                "scope": "DECODED_PNG_CHANNEL_AND_ALPHA_MEASUREMENTS_ONLY",
            }
        ],
        "limitations": [
            "Byte-domain channel statistics; no object classification, detection, OCR or scene understanding.",
            "RGB/RGBA PNG-only; other bit depths, interlaced PNG and other image formats are rejected.",
        ],
    },
    "f31": {
        "version": "0.1.0",
        "operations": [],
        "availability": "UNAVAILABLE",
        "reason": "No tested backend STT/TTS runtime; existing browser Web Speech needs device permission and physical verification.",
        "limitations": [
            "Browser implementation: clients/pwa/voice.mjs; generic audio parsing does not establish speech recognition."
        ],
    },
    "f33": {
        "version": "0.1.0",
        "operations": [],
        "availability": "UNAVAILABLE",
        "reason": "No authorized connected physical device, telemetry adapter or tested action interlock is configured.",
        "limitations": ["No physical actions or fabricated device telemetry."],
    },
}


def _fields(payload, expected):
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("Invalid multimodal payload fields")


def _image_bytes(payload):
    _fields(payload, {"image_base64"})
    value = payload["image_base64"]
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_BASE64_CHARS:
        raise ValueError("Bounded base64 PNG required")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, UnicodeError, ValueError):
        raise ValueError("Strict base64 PNG required") from None
    if len(raw) > MAX_IMAGE_BYTES or not raw.startswith(PNG_SIGNATURE):
        raise ValueError("Bounded PNG required")
    # Reject non-canonical padding and alternative unused trailing bits.
    if base64.b64encode(raw).decode("ascii") != value:
        raise ValueError("Canonical base64 PNG required")
    return raw


def _paeth(left, above, upper_left):
    prediction = left + above - upper_left
    distances = (abs(prediction - left), abs(prediction - above), abs(prediction - upper_left))
    return (left, above, upper_left)[distances.index(min(distances))]


def _decode_png(raw):
    position = len(PNG_SIGNATURE)
    header = None
    compressed = bytearray()
    ended = False
    idat_started = False
    idat_ended = False
    chunk_count = 0
    while position < len(raw):
        chunk_count += 1
        if chunk_count > 4096 or position + 12 > len(raw):
            raise ValueError("Invalid PNG chunks")
        length = struct.unpack_from(">I", raw, position)[0]
        kind = raw[position + 4 : position + 8]
        end = position + 12 + length
        if end > len(raw) or not re.fullmatch(b"[A-Za-z]{4}", kind) or kind[2] & 32:
            raise ValueError("Invalid PNG chunk length or type")
        data = raw[position + 8 : position + 8 + length]
        expected_crc = struct.unpack_from(">I", raw, position + 8 + length)[0]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != expected_crc:
            raise ValueError("PNG checksum mismatch")
        if header is None and kind != b"IHDR":
            raise ValueError("PNG header must be first")
        if kind == b"IHDR":
            if header is not None or length != 13:
                raise ValueError("Invalid PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            if (
                not 1 <= width <= MAX_IMAGE_SIDE
                or not 1 <= height <= MAX_IMAGE_SIDE
                or width * height > MAX_IMAGE_PIXELS
                or depth != 8
                or color not in {2, 6}
                or (compression, filtering, interlace) != (0, 0, 0)
            ):
                raise ValueError("Unsupported or oversized PNG format")
            header = (width, height, 3 if color == 2 else 4)
        elif kind == b"IDAT":
            if idat_ended:
                raise ValueError("PNG image data must be consecutive")
            idat_started = True
            compressed.extend(data)
        elif kind == b"IEND":
            if length or not idat_started or end != len(raw):
                raise ValueError("Invalid PNG end")
            ended = True
            break
        else:
            # No unknown critical chunks, palettes, transparency semantics or
            # animations. Ancillary metadata is CRC checked but not interpreted.
            if not kind[0] & 32 or kind in {b"acTL", b"fcTL", b"fdAT", b"tRNS"}:
                raise ValueError("Unsupported PNG chunk")
            if idat_started:
                idat_ended = True
        position = end
    if not ended or not header or not compressed:
        raise ValueError("Incomplete PNG")
    width, height, channels = header
    stride = width * channels
    expected_size = height * (stride + 1)
    inflater = zlib.decompressobj()
    try:
        decoded = inflater.decompress(bytes(compressed), expected_size + 1)
    except zlib.error:
        raise ValueError("Invalid PNG compressed data") from None
    if len(decoded) != expected_size or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise ValueError("PNG decompression length mismatch")
    pixels = bytearray(width * height * channels)
    prior = bytearray(stride)
    for row_index in range(height):
        source_offset = row_index * (stride + 1)
        filter_kind = decoded[source_offset]
        if filter_kind > 4:
            raise ValueError("Unsupported PNG row filter")
        row = bytearray(decoded[source_offset + 1 : source_offset + stride + 1])
        for column in range(stride):
            left = row[column - channels] if column >= channels else 0
            above = prior[column]
            upper_left = prior[column - channels] if column >= channels else 0
            if filter_kind == 1:
                prediction = left
            elif filter_kind == 2:
                prediction = above
            elif filter_kind == 3:
                prediction = (left + above) // 2
            elif filter_kind == 4:
                prediction = _paeth(left, above, upper_left)
            else:
                prediction = 0
            row[column] = (row[column] + prediction) & 255
        pixels[row_index * stride : (row_index + 1) * stride] = row
        prior = row
    return width, height, channels, pixels


def _inspect_image(payload, *, measure):
    raw = _image_bytes(payload)
    width, height, channels, pixels = _decode_png(raw)
    result = {
        "execution_mode": "DETERMINISTIC",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "format": "PNG",
        "width": width,
        "height": height,
        "pixel_count": width * height,
        "channels": channels,
        "scope": "VALIDATED_PNG_STRUCTURE_AND_DIMENSIONS_ONLY",
    }
    if measure:
        names = ("red", "green", "blue", "alpha")
        result["channel_statistics"] = []
        for index in range(channels):
            values = pixels[index::channels]
            result["channel_statistics"].append(
                {
                    "channel": names[index],
                    "minimum": min(values),
                    "maximum": max(values),
                    "mean": sum(values) / len(values),
                }
            )
        result["opaque_fraction"] = (
            sum(value == 255 for value in pixels[3::4]) / (width * height) if channels == 4 else 1.0
        )
        result["scope"] = "DECODED_PNG_CHANNEL_AND_ALPHA_MEASUREMENTS_ONLY"
    return result


def execute(fabric_id, operation, payload):
    """Execute only fixed bounded operations; no submitted paths, URLs or code."""
    if fabric_id == "f17" and operation == "document.inspect":
        _fields(payload, {"text"})
        text = payload["text"]
        if not isinstance(text, str) or len(text) > 16000:
            raise ValueError("Bounded Unicode text required")
        try:
            raw = text.encode("utf-8")
        except UnicodeError:
            raise ValueError("Valid Unicode text required") from None
        return {
            "execution_mode": "DETERMINISTIC",
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "characters": len(text),
            "utf8_bytes": len(raw),
            "lines": len(text.splitlines()),
            "words": len(text.split()),
            "scope": "SUBMITTED_UNICODE_TEXT_STRUCTURE_ONLY",
        }
    if (fabric_id, operation) in {("f17", "image.inspect"), ("f32", "image.measure")}:
        return _inspect_image(payload, measure=fabric_id == "f32")
    if fabric_id in {"f31", "f33"}:
        raise ValueError("Fabric execution unavailable: " + CONTRACTS[fabric_id]["reason"])
    raise ValueError("Unsupported multimodal fabric operation")
