import json
from app.portfolio_relay import PortfolioRelayPoller


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.payload).encode()


class Fabric:
    def __init__(self): self.events = []
    def ingest(self, event): self.events.append(event); return {"accepted": True}


def test_relay_claim_ingest_and_ack():
    requests = []
    event = {"event_id": "event-0001"}
    def opener(request, timeout):
        requests.append((request.method, request.full_url, request.data))
        return Response({"events": [event]} if request.method == "GET" else {"ok": True, "acknowledged": 1})
    fabric = Fabric()
    poller = PortfolioRelayPoller(fabric, url="https://portal.example/api/portfolio-relay", token="secret", interval_seconds=15, opener=opener)
    assert poller.pull_once() == {"claimed": 1, "ingested": 1, "acknowledged": 1}
    assert fabric.events == [event]
    assert requests[0][0] == "GET" and requests[1][0] == "POST"
    assert json.loads(requests[1][2]) == {"action": "ack", "event_ids": ["event-0001"]}


def test_disabled_relay_is_noop():
    assert PortfolioRelayPoller(Fabric(), url="", token="").pull_once() == {"claimed": 0, "ingested": 0, "acknowledged": 0}
