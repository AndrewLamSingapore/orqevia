import pytest

from app import web_search

SAMPLE = (
    '<html><body>'
    '<a rel="nofollow" class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fone">One Title</a>'
    '<a class="result__snippet">Snippet one here.</a>'
    '<a rel="nofollow" class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Ftwo">Two Title</a>'
    '<a class="result__snippet">Snippet two <b>bold</b> here.</a>'
    '</body></html>'
)


class FakeResponse:
    def __init__(self, text="", data=None):
        self.text = text
        self._data = data
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class FakeHttpx:
    def __init__(self, get_response, post_response=None, post_json=None):
        self.get_response = get_response
        self.post_response = post_response
        self.post_json = post_json

    def get(self, url, **kwargs):
        return self.get_response

    def post(self, url, **kwargs):
        self.post_json = kwargs.get("json")
        return self.post_response


def test_duckduckgo_default(monkeypatch):
    monkeypatch.delenv("ORQEVIA_TAVILY_API_KEY", raising=False)
    fake = FakeHttpx(FakeResponse(text=SAMPLE))
    monkeypatch.setattr(web_search, "httpx", fake)
    result = web_search.search("hello", 3)
    assert result["provider"] == "duckduckgo"
    assert [r["url"] for r in result["results"]] == [
        "https://example.com/one",
        "https://example.org/two",
    ]
    assert result["results"][1]["snippet"] == "Snippet two bold here."


def test_tavily_when_key_set(monkeypatch):
    monkeypatch.setenv("ORQEVIA_TAVILY_API_KEY", "tvly-fixture-key")
    fake = FakeHttpx(
        FakeResponse(),
        post_response=FakeResponse(data={"results": [{"title": "T", "url": "https://x.test", "content": "c"}]}),
    )
    monkeypatch.setattr(web_search, "httpx", fake)
    result = web_search.search("hello", 2)
    assert result["provider"] == "tavily"
    assert fake.post_json["api_key"] == "tvly-fixture-key"
    assert result["results"][0]["url"] == "https://x.test"


def test_validation():
    with pytest.raises(ValueError):
        web_search.search("")
    with pytest.raises(ValueError):
        web_search.search("x" * 401)
    with pytest.raises(ValueError):
        web_search.search("hello", 9)
