"""Owner-local PXI read model. No recurring monitoring starts on import."""
import os
from pathlib import Path

from .evidence_product import EvidenceLedger
from .exposure_intelligence import ExposureIntelligence


def exposure_view():
    path = Path(os.getenv('PRIME_DATA_DIR', '/data')) / 'evidence-lens.db'
    if not path.is_file():
        findings, alerts, semantic = [], [], {'verification': 'VERIFY_REQUIRED', 'relations': []}
    else:
        service = ExposureIntelligence(EvidenceLedger(path, read_only=True))
        findings, alerts, semantic = service.findings(), service.alerts(), service.semantic_projection()
    return {'schema_version': 'prime.pxi.v1', 'domain': 'EXPOSURE_EVIDENCE',
            'mode': 'READ_ONLY', 'findings': findings, 'alerts': alerts,
            'semantic': semantic, 'provider_connectivity': 'NOT_PROBED_BY_VIEW',
            'monitoring_active': False, 'commercial_readiness': 'NOT_PRODUCTION_QUALIFIED',
            'missing_integrations': ['POSI_DOMAIN_ADAPTER', 'PGI_DOMAIN_ADAPTER',
                                     'CUSTOMER_ENTITLEMENT_AND_BILLING'],
            'permanent_agents_added': 0}
