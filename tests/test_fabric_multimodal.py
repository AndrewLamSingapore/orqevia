"""Independent pixel oracles and malformed/decompression boundary checks."""

import base64
import hashlib
import struct
import zlib

import pytest

from app.fabric_multimodal import CONTRACTS, MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS, PNG_SIGNATURE, execute


def chunk(kind, value):
    return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)


def png(*, width=2, height=1, color=2, rows=b"\x00\xff\x00\x00\x00\x00\xff", depth=8, interlace=0, compressed=None):
    header = struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace)
    return (
        PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", compressed or zlib.compress(rows)) + chunk(b"IEND", b"")
    )


def payload(raw):
    return {"image_base64": base64.b64encode(raw).decode()}


def measure(raw):
    return execute("f32", "image.measure", payload(raw))


def test_actual_rgb_pixel_measurement_and_provenance():
    raw = png()
    result = measure(raw)
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert (result["width"], result["height"], result["pixel_count"], result["channels"]) == (2, 1, 2, 3)
    assert result["channel_statistics"] == [
        {"channel": "red", "minimum": 0, "maximum": 255, "mean": 127.5},
        {"channel": "green", "minimum": 0, "maximum": 0, "mean": 0},
        {"channel": "blue", "minimum": 0, "maximum": 255, "mean": 127.5},
    ]
    assert result["opaque_fraction"] == 1.0
    assert result["execution_mode"] == "DETERMINISTIC"
    assert "MEASUREMENTS_ONLY" in result["scope"]


def test_actual_alpha_measurement_has_partial_opacity():
    result = measure(png(color=6, rows=b"\x00\x0a\x14\x1e\xff\x6e\x78\x82\x00"))
    assert result["channels"] == 4
    assert result["opaque_fraction"] == 0.5
    assert [row["mean"] for row in result["channel_statistics"]] == [60, 70, 80, 127.5]


@pytest.mark.parametrize(
    "rows",
    [
        # Two rows are RGB(10,20,30),(40,50,60) and RGB(70,80,90),(100,110,120).
        b"\x00\x0a\x14\x1e\x28\x32\x3c\x00\x46\x50\x5a\x64\x6e\x78",
        b"\x01\x0a\x14\x1e\x1e\x1e\x1e\x01\x46\x50\x5a\x1e\x1e\x1e",
        b"\x02\x0a\x14\x1e\x28\x32\x3c\x02\x3c\x3c\x3c\x3c\x3c\x3c",
        b"\x03\x0a\x14\x1e\x23\x28\x2d\x03\x41\x46\x4b\x2d\x2d\x2d",
        b"\x04\x0a\x14\x1e\x1e\x1e\x1e\x04\x3c\x3c\x3c\x1e\x1e\x1e",
    ],
)
def test_each_png_row_filter_against_known_pixel_oracle(rows):
    result = measure(png(height=2, rows=rows))
    assert [row["mean"] for row in result["channel_statistics"]] == [55.0, 65.0, 75.0]
    assert [row["minimum"] for row in result["channel_statistics"]] == [10, 20, 30]
    assert [row["maximum"] for row in result["channel_statistics"]] == [100, 110, 120]


def test_inspection_reports_validated_image_scope_without_inference_claim():
    result = execute("f17", "image.inspect", payload(png()))
    assert result["format"] == "PNG" and result["width"] == 2
    assert "channel_statistics" not in result
    assert "ONLY" in result["scope"]


def test_text_inspection_counts_unicode_and_preserves_hash_without_echoing_content():
    text = "Hello world\n\u661f \u7a7a"
    result = execute("f17", "document.inspect", {"text": text})
    assert result["characters"] == len(text)
    assert result["utf8_bytes"] == len(text.encode("utf-8"))
    assert result["source_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result["lines"] == 2 and result["words"] == 4
    assert text not in str(result)
    assert execute("f17", "document.inspect", {"text": ""})["lines"] == 0


@pytest.mark.parametrize(
    "value", [{}, {"text": 3}, {"text": "x", "path": "/secret"}, {"text": "\ud800"}, {"text": "x" * 16001}]
)
def test_document_invalid_payloads_rejected(value):
    with pytest.raises(ValueError):
        execute("f17", "document.inspect", value)


@pytest.mark.parametrize("value", ["", "not png", "data:image/png;base64,AA==", "AA==\n", "AB==", "\u4e2d", None, 5])
def test_invalid_base64_or_non_png_rejected(value):
    with pytest.raises(ValueError):
        execute("f32", "image.measure", {"image_base64": value})


def test_file_and_payload_bounds():
    with pytest.raises(ValueError):
        execute("f32", "image.measure", payload(PNG_SIGNATURE + b"x" * MAX_IMAGE_BYTES))
    with pytest.raises(ValueError):
        execute("f32", "image.measure", {**payload(png()), "url": "http://localhost"})


@pytest.mark.parametrize(
    "raw",
    [
        png(width=0),
        png(width=2049),
        png(width=513, height=513),
        png(color=0),
        png(color=3),
        png(depth=16),
        png(interlace=1),
        png(rows=b"\x05\x00\x00\x00\x00\x00\x00"),
        png(rows=b"\x00\x00"),
        png(rows=b"\x00" * 8),
        png(compressed=zlib.compress(b"\x00" * 7) + b"trailing"),
        png(compressed=zlib.compress(b"\x00" * 7)[:-1]),
        png(compressed=b"not zlib"),
        png()[:-1],
        png() + b"trailing",
    ],
)
def test_malformed_and_unsupported_pngs_rejected(raw):
    with pytest.raises(ValueError):
        measure(raw)


def test_compressed_bomb_rejected_without_expanding_beyond_declared_pixels():
    raw = png(width=1, height=1, compressed=zlib.compress(b"\x00" * 4_000_000))
    assert len(raw) < MAX_IMAGE_BYTES
    with pytest.raises(ValueError, match="decompression length"):
        measure(raw)


def test_checksum_tamper_rejected():
    raw = bytearray(png())
    raw[19] ^= 1
    with pytest.raises(ValueError, match="checksum"):
        measure(bytes(raw))


@pytest.mark.parametrize("kind", [b"ABCD", b"acTL", b"fcTL", b"fdAT", b"tRNS"])
def test_unknown_critical_or_animation_transparency_chunks_rejected(kind):
    raw = png()
    raw = raw[:33] + chunk(kind, b"test") + raw[33:]
    with pytest.raises(ValueError):
        measure(raw)


def test_crc_checked_ancillary_metadata_and_consecutive_idat_rules():
    raw = png()
    assert measure(raw[:33] + chunk(b"tEXt", b"Test\x00untrusted") + raw[33:])["pixel_count"] == 2
    malformed = raw[:-12] + chunk(b"tEXt", b"break") + chunk(b"IDAT", b"") + raw[-12:]
    with pytest.raises(ValueError, match="consecutive"):
        measure(malformed)


def test_unknown_operation_and_unavailable_runtimes_are_not_passed():
    for fabric_id, operation in [
        ("f32", "object.detect"),
        ("f17", "audio.transcribe"),
        ("f31", "speech.recognize"),
        ("f33", "move"),
    ]:
        with pytest.raises(ValueError):
            execute(fabric_id, operation, {})
    assert CONTRACTS["f31"]["availability"] == CONTRACTS["f33"]["availability"] == "UNAVAILABLE"
    assert CONTRACTS["f31"]["operations"] == CONTRACTS["f33"]["operations"] == []
    assert MAX_IMAGE_PIXELS == 262144
