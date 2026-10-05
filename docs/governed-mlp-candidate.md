# Governed local MLP candidate

This branch adds a small CPU MLP for bounded numeric tabular data. It has no
PyTorch, scikit-learn, ONNX, Hugging Face, network, GPU, or pickle dependency.
Its code is independent of the LLM gateway. No existing inference task is
automatically routed to it.

`app.mlp_fabric.train_candidate` validates named numeric features and labels,
uses a seeded 60/20/20 split, fits standardization on training rows only,
trains a configurable one-output network, evaluates validation and test
partitions, compares a linear or logistic baseline trained on the same training
partition, and returns a JSON candidate. Binary classification and scalar
regression are supported. Hidden layers, activation, seed, epochs, and learning
rate are bounded. Categorical values, missing values, non-finite numbers,
unknown fields, and malformed shapes are rejected. Inference binds values by
the artifact's ordered feature names.

`approve_candidate` requires an independent approval receipt and an injected
verification callback. A reviewer string by itself cannot approve a model.
Registration verifies the receipt again and fails closed when no verifier is
configured. The callback must be supplied by PRIME's authority integration,
outside the executing agent's control. JSON loading validates version,
provenance, metrics, tensor shapes, and the SHA-256 identity of the immutable
model body. Runtime inference
uses only registered models and records latency, failures, and validation
failures without recording input rows. Separate `evaluate` calls return metrics
for new labeled data and require review; they never retrain or change a model.
Agent invocation requires an independently verified decision for the exact
`ml.mlp.classification` or `ml.mlp.regression` capability, agent, model hash,
and trace, as well as the existing healthy certification route. The decision
verifier also fails closed when unconfigured. The result carries model
identity, decision ID, and provenance.

The synthetic tests demonstrate actual CPU training and inference for a
quadratic regression and an XOR-like classification. Both beat their simple
linear or logistic comparators on held-out fixtures. The agent-path test uses
a synthetic L7 projection to verify the software gate; it is not evidence that
a real agent is currently L7 certified. No live ABEX inference, approved
production artifact, durable model registry, or HTTP routing was changed by
this branch. Real agent acceptance must bind an independently verified live
certification projection and authority and approval receipt verifiers, persist the approved artifact
in the owning artifact system, and record a live runtime receipt. Those remain
integration work before production promotion.
