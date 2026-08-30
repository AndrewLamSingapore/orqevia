from app.orchestration import has_consequential_intent


def test_consequential_send_variants_are_gated():
    assert has_consequential_intent('send message', '')
    assert has_consequential_intent('send an external message', '')
    assert has_consequential_intent('please send the customer an email', '')


def test_consequential_account_and_money_variants_are_gated():
    assert has_consequential_intent('transfer the payment', '')
    assert has_consequential_intent('change my account password', '')
    assert has_consequential_intent('delete the remote record', '')


def test_internal_planning_is_not_gated_by_itself():
    assert not has_consequential_intent('research architecture and write an internal plan', '')
