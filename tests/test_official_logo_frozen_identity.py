"""Logo assets must not alter role prompts, normal oracle observer or client state."""
import hashlib
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
BASELINE={
  "app/product_identity.py": "9b435157d7b4f7529ba7df5b1ad4fa60df1df2c38fa6e77aa953b6497d19566c",
  "app/agent_dispatch_api.py": "089f7fade8c3e3c4290c6e7a46c904e586611dd1230e18c2fd45fdafc7b1a2b6",
  "app/jarvis_response_contract.py": "2fa5dc630a9859db2d28d21d8ac613b60d3e5c6e5de4fe2ccc0dd4309708e4bb",
  "app/agent_registry.py": "0fa4ea02a9528f1319b03e1e007b86bd636ced09f3d0138bb3f56c584f51ffe7",
  "app/agent_coaching.py": "47be64e4c94647a81f5da290a6149e576657748087cdc5dfa3f4086400babf9f",
  "app/normal_latest_observation.py": "d6ee8da91069d7eebe2807cb6a67869bcf9ed62efb9382f1a1374e2ec7a441ad",
  "app/pwa_sessions.py": "803c816ed6ca301be5278d5a595b6a88a668f542e347dc325f7c035306050aba",
  "clients/pwa/storage.mjs": "1a5d86fa99547c0357fea231fd0b322df37152b5a5327661e41aa1e423cbb9c5",
  "clients/pwa/core.mjs": "ef093a343de66235a8baa3303e7c8cf79e55d0487b90b9183c4ca3eb28861c08",
  "clients/pwa/app.mjs": "d5df2aa5b44e0aedda4cca67decd2574e8adb48f64b7c722a61a34a821741cf8",
  "clients/pwa/dashboard.mjs": "36f2eb1c3c73be6151c3b9ad9b6e9f96e1e6917205163d2d28ad78d0e14c6e5c",
  "clients/pwa/voice.mjs": "358d471c14a1c14b0e0c69680eafad4f4e1851051e78caad01002d47364eebf0",
  "config/agent_registry.json": "dbeb03afaeceaf47e59645958b383e579597f10441a723f0d22375fbc5c208d6",
  "config/agent_registry_migration.json": "e328d9e3182881e5310aa73967add1f529ebbcef0aed33aa64727c683310c4a9"
}

@pytest.mark.parametrize('name',sorted(BASELINE))
def test_official_logo_preserves_identity_cohort_and_client_state(name):
    raw=(ROOT/name).read_bytes().replace(b'\r\n',b'\n')
    assert hashlib.sha256(raw).hexdigest()==BASELINE[name]
