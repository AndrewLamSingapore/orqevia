# Dell changed-scope runtime verification handoff — 2026-09-26

Status: **READY FOR READ-ONLY INDEPENDENT VERIFICATION**

This handoff does not restart the historical 36-capability campaign. Dell must
verify only the changed and consequential production gates below. Dell must not
modify ABEX, enroll another identity, create a replacement task, or infer runtime
acceptance from model prose.

## Candidate receipt

- ABEX observation: `docs/evidence/ABEX_RUNTIME_RECEIPT_D0970FC_20260926.json`
- Production source: `d0970fcf497f6f36baad90cf160e490f7e4745bb`
- Immutable image: `prime:sha-d0970fc`
- Image ID: `sha256:daf36b01db786ab5dd63149348d7dc532b3695e8a13ac9bbf2bf0a210eecdcfe`
- Registry: schema `2.0`, version `1.0.0`, 21 logical agents,
  SHA-256 `fec92b1d0e3e858bc5f4fe1b26401d053ee94b9b2358be8da379b97884d916ff`
- Physical task: `0fbc896f-5fb6-4808-9eab-93031cf55873`
- Bound artifact: `aa85a93e1b7e4757805896500c070b9c`, SHA-256
  `2a0f32c1a4022e24d7d32b8e2d50e969f441fa8e062cfab1edbb76aa3ec2e2bf`

## Read-only verification scope

1. Fetch the receipt from the exact remote commit supplied after publication and
   verify its bytes/hash before evaluating its claims.
2. From Dell's existing authenticated Owner session, reread the same task. Verify
   task UUID, COMPLETED state, lifecycle ordering, runtime source SHA/image digest,
   Chinese result, artifact binding, and zero model/system contradictions.
3. Verify the runtime record says ABEX, not Dell, and the selected agent's role and
   capability are registry-bound. Model content must remain non-authoritative and
   must not grant authority, verification, identity, timestamps, or digests.
4. Verify normal PWA navigation, same-task deep link/refresh, source-served PWA
   asset identity, authenticated access, spoofed/cross-site denial, and LAN-only
   exposure. Do not disable TLS verification.
5. Compare the receipt's registry identity, 21-agent count, runtime SHA, image
   digest, artifact digest, and task identity with independently observed values.

Return a machine-readable result containing the exact receipt SHA-256, verifier
identity `DELL-INDEPENDENT-VERIFIER`, observation time, each check as PASS/FAIL,
and an overall PASS only when every required check passes. A Dell result must not
itself mutate ABEX or `prime.state`; ABEX consumes it through the canonical SSOT
review after verifying the result and its provenance.

The already completed physical task-open test is retained as Owner physical
evidence and need not be repeated unless this verification detects a regression.
