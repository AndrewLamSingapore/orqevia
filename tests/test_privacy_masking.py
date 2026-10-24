from app.privacy_masking import mask_email, mask_phone, mask_text, mask_token


def test_mask_email():
    assert mask_email("alice@example.com") == "a***e@example.com"


def test_mask_phone():
    assert mask_phone("+65 9123 4567") == "***-***-4567"


def test_mask_token():
    assert mask_token("tvly-abcdefgh") == "tvly***"


def test_mask_text():
    masked = mask_text("mail alice@example.com call +65 9123 4567 token Bearer abcdefgh12345")
    assert "alice@example.com" not in masked
    assert "9123 4567" not in masked
    assert "abcdefgh12345" not in masked
    assert "a***e@example.com" in masked
