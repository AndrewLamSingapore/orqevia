# MBTI-in-Thoughts 1.0.0

This directory contains the reviewed upstream wheel used by ORQEVIA.

- Source: <https://github.com/spcl/MBTI-in-Thoughts>
- Source revision: `ba760ed73b9592798c964ad64db11a1ca4c7ce8f`
- Distribution: `MBTI-in-Thoughts==1.0.0`
- Official upstream wheel: `mbti_in_thoughts-1.0.0-py3-none-any.whl`
- Official wheel SHA-256:
  `b833d4f8f9529d7d84d869ce6394a9ab260332d8248f1bf5fa6798c05954c5e6`
- ORQEVIA runtime wheel:
  `mbti_in_thoughts-1.0.0-1orqevia-py3-none-any.whl`
- Runtime wheel SHA-256:
  `d44559e35f720cb3295b5dcc13ca95c33343da5e3c81a1743a234ce1617d2af8`
- License: BSD-style, copied to the runtime package under
  `mbti_in_thoughts/licenses/MBTI-in-Thoughts-LICENSE.txt`

The official wheel was built from the pinned source with Python 3.12 using
`pip wheel --no-deps .`. ORQEVIA then repacks it with
`scripts/repack_mit_runtime_wheel.py`, which removes only the research
`Requires-Dist` metadata and rebuilds the wheel `RECORD`; upstream package
files and version `1.0.0` are unchanged. The runtime wheel is installed into
the image with `pip install --no-deps`, and `pip check` reports no broken
requirements.

The upstream project locks a large research environment, including Torch,
NVIDIA CUDA packages, LangChain and provider SDKs. Installing that lock set
would downgrade ORQEVIA's production dependency closure. The upstream wheel is
therefore installed without transitive dependencies. ORQEVIA's own runtime
provides inference, storage and security; the upstream package supplies
provenance plus the priming data exposed by `mbti_in_thoughts`.

The upstream priming file `priming/priming_without_mention_of_mbti.json` is
retained at `mbti_in_thoughts/data/priming_without_mention_of_mbti.json` in the
reviewed CRLF checkout form. Git preserves those pinned bytes on every platform.
Its text content matches the pinned upstream revision; the upstream LF file has
SHA-256 `3018d73190fb50d739a00192436a665db262359f5a5b266240d8bb497a5411cf`.

- Profile-data SHA-256:
  `bcc7338677d5295259e2041b8e7e8fed7c2d7349a356aa06bf0e49ad82838258`

Installation does not activate behavioral conditioning. A profile must still
be explicitly enabled per agent through ORQEVIA's governed API, and the
existing safety precedence remains enforced.
