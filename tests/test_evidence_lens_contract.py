from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class LensParser(HTMLParser):
    def __init__(self): super().__init__(); self.tags=[]
    def handle_starttag(self,tag,attrs): self.tags.append((tag,dict(attrs)))


def test_lens_has_accessible_progressive_disclosure_and_mobile_contract():
    text=(ROOT/'examples/evidence-lens/index.html').read_text(encoding='utf-8')
    parser=LensParser(); parser.feed(text)
    buttons=[attrs for tag,attrs in parser.tags if tag=='button']
    assert len(buttons)==2 and all(item.get('role')=='tab' and item.get('aria-controls') for item in buttons)
    assert 'role="tabpanel"' in text and '<details>' in text and '<summary>' in text
    assert '@media(max-width:520px)' in text and 'Overall: FAILED' in text
    assert 'Service is available — CONTRADICTED' in text
    assert '<script src=' not in text and 'eval(' not in text and 'innerHTML' not in text


def test_lens_is_portable_and_does_not_query_prime():
    text=(ROOT/'examples/evidence-lens/index.html').read_text(encoding='utf-8').lower()
    assert '/api/' not in text and 'prime.db' not in text and 'owner:' not in text
