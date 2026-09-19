from copy import deepcopy

import pytest

from app.host_guard import EffectClass, classify_effect, effect_digest, enforce_at_execution


def envelope(command="", *, action="executor.run", declared=None, approval=True):
    value = {
        "action": action,
        "parameters": {"executable": "powershell.exe", "arguments": command, "target": "fixture"},
        "context": {},
        "authorization": {"owner_approval_id": "owner-fixture" if approval else None},
    }
    if declared:
        value["context"]["effect_class"] = declared
    value["context"]["approved_effect_digest"] = effect_digest(value)
    return value


@pytest.mark.parametrize("command,expected", [
    ("Format-Volume -DriveLetter X", EffectClass.STORAGE_DESTRUCTIVE),
    ("Clear-Disk -Number 9", EffectClass.STORAGE_DESTRUCTIVE),
    ("diskpart /s generated.txt & rem create partition primary", EffectClass.STORAGE_DESTRUCTIVE),
    ("cmd.exe /c powershell -File wrapper.ps1 chkdsk X: /f", EffectClass.STORAGE_DESTRUCTIVE),
    ("bcdedit /delete {fixture}", EffectClass.BOOT_DESTRUCTIVE),
    ("powershell -Command Invoke-CimMethod firmware update", EffectClass.FIRMWARE_DESTRUCTIVE),
    ("Remove-Item C:\\fixture\\recovery -Recurse", EffectClass.STORAGE_DESTRUCTIVE),
    ("git push --force origin main", EffectClass.STORAGE_DESTRUCTIVE),
])
def test_destructive_effects_are_detected_through_wrappers(command, expected):
    assert classify_effect(envelope(command)) == expected


def test_unknown_privileged_effect_fails_closed_without_exact_approval():
    value = envelope("harmless-fixture", approval=False)
    with pytest.raises(PermissionError, match="explicit owner approval"):
        enforce_at_execution(value)

    value = envelope("harmless-fixture")
    value["context"]["approved_effect_digest"] = "stale"
    with pytest.raises(PermissionError, match="exact execution effect"):
        enforce_at_execution(value)


def test_target_substitution_invalidates_approval():
    value = envelope("fixture command")
    assert enforce_at_execution(value) == EffectClass.HOST_HIGH_RISK
    changed = deepcopy(value)
    changed["parameters"]["target"] = "different-device"
    with pytest.raises(PermissionError, match="exact execution effect"):
        enforce_at_execution(changed)


def test_agent_cannot_self_declare_lower_risk():
    value = envelope("Format-Volume -DriveLetter X", declared="READ_ONLY")
    with pytest.raises(PermissionError, match="lower"):
        enforce_at_execution(value)


def test_safe_read_and_application_mutation_remain_available():
    read = envelope("", action="web.search", approval=False)
    artifact = envelope("", action="artifact.create", approval=False)
    assert enforce_at_execution(read) == EffectClass.READ_ONLY
    assert enforce_at_execution(artifact) == EffectClass.APPLICATION_MUTATION
