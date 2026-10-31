# Cost optimization matrix

Local inference has no per-token external API charge, but electricity, existing
hardware, Windows workloads, storage and any subscriptions still cost resources.
Actual electricity, tariffs, cloud invoices and subscriptions are NOT VERIFIED.
No fixed monthly cloud cost can be inferred from Docker metadata.

| Option | External inference charge | Local resource cost | Measured quality/performance |
|---|---|---|---|
| Existing local dense models | $0 for local calls | Current CPU/RAM observations; power unknown | Historical job completions and failures, not a controlled benchmark |
| Selective-agent local design | $0 for local calls | Savings depend on avoided repeated work; current default already selects one agent | NOT VERIFIED after deployment |
| Native local MoE | $0 for local calls; acquisition/network costs unknown | Full weights+KV+runtime; CPU speed unknown | NOT BENCHMARKED |
| Hybrid selective escalation | Token-priced external calls plus any applicable service fees | Lower local workload possible; no observed savings yet | Task-quality and privacy validation required |

For N missions/month, cloud fraction f, average billable input I and output O,
and prices Pi/Po in USD per million tokens:

`monthly_API_USD = N * f * (I*Pi + O*Po) / 1,000,000`

Include router/classifier, verification, retries, tool/search fees and multiple
specialist calls in I/O totals. Count avoided calls once; a cache hit is not an
additional saving on top of the same deduplicated call.

Illustration only, not provider pricing: at I=2000,O=500,Pi=$1,Po=$4,
each cloud mission costs$0.004. With10% escalation:

| Total monthly missions | All cloud under illustration | 10% cloud under illustration |
|---:|---:|---:|
| 100 | $0.40 | $0.04 |
| 1000 | $4.00 | $0.40 |
| 10000 | $40.00 | $4.00 |

This is not a forecast of ABEX's workload or a quote for a flagship model.

The existing catalog's Gemma3-4B classification route lists$0.05/M input and
$0.10/M output. [DeepInfra's public model page](https://deepinfra.com/google/gemma-3-4b-it)
currently displays those standard rates. At2000 input/500 output tokens this is
$0.00015 per call before any applicable router/account charges. This narrow
classification model is not a validated high-difficulty reasoning substitute.
Actual Hugging Face routing charges, credits and invoices remain NOT VERIFIED.

Configured job/day ceilings are accounting settings, not proof every execution
path enforces them. Current cloud usability and runtime policy drift must be
checked separately. No paid acceptance call was made.
