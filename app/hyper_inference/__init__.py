"""ORQEVIA Hyper-Inference Fabric.

Advisory-only, deterministic coordination layer for reasoning engines,
inference channels, model/tool proxies, intelligence matrices and the adaptive
inference router. This package never executes consequential actions, never
grants authority, and never assumes all agents share permissions.
"""

from .engines import (
    ENGINE_SPECS,
    EngineResult,
    InferenceEngineRegistry,
    run_engine,
)
from .channels import (
    CHANNEL_SPECS,
    ChannelResult,
    InferenceChannelRegistry,
    run_channel,
)
from .proxies import (
    ExecutionReceipt,
    ModelProxyRegistry,
    ProviderSpec,
    ToolProxyRegistry,
    ToolSpec,
)
from .matrices import (
    CapabilityMatrix,
    ConfidenceStore,
    KnowledgeGraph,
    ProvenanceLedger,
    RelationalMatrix,
    VectorStore,
)
from .router import AdaptiveInferenceRouter, RouterResult

__all__ = [
    "ENGINE_SPECS",
    "CHANNEL_SPECS",
    "EngineResult",
    "ChannelResult",
    "RouterResult",
    "ExecutionReceipt",
    "InferenceEngineRegistry",
    "InferenceChannelRegistry",
    "ModelProxyRegistry",
    "ToolProxyRegistry",
    "ProviderSpec",
    "ToolSpec",
    "CapabilityMatrix",
    "ConfidenceStore",
    "KnowledgeGraph",
    "ProvenanceLedger",
    "RelationalMatrix",
    "VectorStore",
    "AdaptiveInferenceRouter",
    "run_engine",
    "run_channel",
]
