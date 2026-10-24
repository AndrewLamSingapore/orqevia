"""Invalid speech requests never invoke a command; no fake synthesis evidence."""

from unittest.mock import patch
import pytest
from app.fabric_speech import synthesize


@pytest.mark.parametrize(
    "text,voice",
    [
        ("", "Microsoft David Desktop"),
        ("x" * 121, "Microsoft David Desktop"),
        ("ok", "arbitrary shell"),
        ("\x00", "Microsoft David Desktop"),
        (None, "Microsoft David Desktop"),
    ],
)
def test_invalid_speech_never_invokes_process(text, voice):
    with patch("app.fabric_speech.subprocess.run") as command:
        with pytest.raises(ValueError):
            synthesize(text, voice)
    command.assert_not_called()
