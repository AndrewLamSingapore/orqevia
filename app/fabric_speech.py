"""Offline installed Windows voice synthesis; no model/provider downloads.

Only the private Windows knowledge service calls this module. Text enters the
fixed PowerShell program through JSON stdin and is never interpreted as code.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import threading
import wave

VOICES = ("Microsoft David Desktop", "Microsoft Zira Desktop")
SLOT = threading.BoundedSemaphore(1)
PROGRAM = r"""
$ErrorActionPreference = 'Stop'
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$stream = New-Object System.IO.MemoryStream
try {
  $speaker.SelectVoice([string]$request.voice)
  $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
  $speaker.SetOutputToAudioStream($stream, $format)
  $speaker.Speak([string]$request.text)
  $speaker.SetOutputToNull()
  [Convert]::ToBase64String($stream.ToArray())
} finally {
  $speaker.Dispose()
  $stream.Dispose()
}
"""


def synthesize(text: str, voice: str = VOICES[0]) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 120 or "\x00" in text or voice not in VOICES:
        raise ValueError("Speech text or voice exceeds the supported contract")
    text.encode("utf-8")
    if os.name != "nt":
        raise RuntimeError("Installed Windows speech runtime required")
    if not SLOT.acquire(blocking=False):
        raise RuntimeError("Speech capacity is in use")
    try:
        process = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PROGRAM],
            input=json.dumps({"text": text, "voice": voice}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if process.returncode != 0 or len(process.stdout) > 1_500_000:
            raise RuntimeError("Installed voice did not synthesize within its output contract")
        pcm = base64.b64decode(process.stdout.strip(), validate=True)
        if not pcm or len(pcm) > 1_000_000 or len(pcm) % 2:
            raise RuntimeError("Invalid bounded PCM speech output")
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm)
        raw = output.getvalue()
        if not any(pcm):
            raise RuntimeError("Speech output is empty audio")
        return {
            "audio_base64": base64.b64encode(raw).decode("ascii"),
            "audio_sha256": hashlib.sha256(raw).hexdigest(),
            "mime_type": "audio/wav",
            "frames": len(pcm) // 2,
            "sample_rate_hz": 16000,
            "channels": 1,
            "sample_width_bytes": 2,
            "duration_seconds": len(pcm) / 32000,
            "voice": voice,
            "engine": "WINDOWS_SYSTEM_SPEECH_OFFLINE",
            "paid_provider_called": False,
            "speech_recognition_supported": False,
        }
    except (ValueError, UnicodeError, subprocess.TimeoutExpired):
        raise RuntimeError("Speech synthesis did not complete its bounded operation") from None
    finally:
        SLOT.release()
