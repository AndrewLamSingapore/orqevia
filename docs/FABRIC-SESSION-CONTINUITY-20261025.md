# Production fabric session continuity

The HTTPS fabric workbench must retain its selected operation, inputs and
execution recovery state when a valid device session renews. Admission policy
and cookie transport are separate contracts.

The 25 October production investigation found that unrestricted admission set
`Secure=False` on `__Host-ORQEVIA-PWA` and `__Host-ORQEVIA-Device`. Chromium
rejects cookies with that prefix unless they have `Secure`, `Path=/`, and no
`Domain`. The next 60-second session check therefore admitted a new identity;
the workbench correctly cleared the previous identity's private form state.

The fix emits and expires both current and legacy cookie names with `Secure`,
`HttpOnly`, `SameSite=Strict`, `Path=/`, and no `Domain`, in every admission
mode. It changes no owner role, pairing decision, server identity or stored
credential. Existing trusted browser profiles and databases remain in place.

Regression evidence must include browser acceptance of the cookie flags,
the same identity before and after session renewal, preservation of an edited
fabric form across the renewal, and actual persisted execution readback through
HTTPS. HTTP test-client cookie jars alone do not enforce browser prefix rules.

The original runtime at `c281cc8a26c8e64ce7a2b27a80c82abaad0a72fc` passed
36 scoped fabric oracles and all 43 input/output operation contracts through
the production gateway. Its initial UI test failure remains a separate receipt.
Successful backend execution never conceals a failed browser journey.

Rollback uses the retained exact pre-change image and current databases,
without deleting sessions, device trust, certificate material or user data.
The exposed HTTP bootstrap remains retired. Private internal transports are
outside this cookie repair.

References: [browser cookie prefix contract](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie#cookie_prefixes).
