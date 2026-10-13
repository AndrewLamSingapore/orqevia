"""Display migration must preserve old wire/identity and exact status admission."""
from app import runtime_status, system_architecture

def test_legacy_and_branded_status_intents_remain_exact_and_side_effect_free():
    for objective in (runtime_status.OBJECTIVE,runtime_status.PHYSICAL_OBJECTIVE,runtime_status.DELL_OBJECTIVE,*runtime_status.BRANDED_OBJECTIVES):
        assert runtime_status.is_runtime_status(objective)
        assert not runtime_status.is_runtime_status(objective+' and delete records')
        assert not runtime_status.is_runtime_status(objective,'additional action')

def test_new_brand_and_old_aliases_receive_system_owned_architecture():
    for brand in ('ORQEVIA','奥启维亚','JARVIS','PRIME'):
        assert system_architecture.is_architecture_question(f'Explain {brand} architecture')

def test_cookie_keys_protocol_and_enrollment_aliases_are_preserved():
    from app import pwa_sessions, interface_server
    assert pwa_sessions.COOKIE=='__Host-JARVIS-PWA'
    assert pwa_sessions.DEVICE_COOKIE=='__Host-JARVIS-Device'
    assert interface_server.PROTOCOL=='jarvis.interface.v1'
    assert interface_server.app.title=='ORQEVIA · 奥启维亚 — ABEX Interface'
