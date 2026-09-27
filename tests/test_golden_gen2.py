from scripts.verify_golden_gen2 import validate

def test_golden_gen2_binds_runtime_and_preserves_audio_failure():
    assert validate() == []
