# PDE isolated development evidence — 2026-10-02 SGT

This is an isolated candidate, not a production deployment or acceptance.

## Preserved failure

The first 11-test run had 10 passing tests and one error on Windows:
`test_known_brier_and_leakage_guard` could not remove its temporary
`forecast.sqlite` because the file remained in use (WinError 32). The cause was
using the SQLite connection as a transaction context manager, which does not
close the connection. The implementation was changed to explicitly close each
connection, while retaining transactional writes. The test was not weakened.

## Boundaries

PDE currently supports only a bounded discrete decision core, binary Bayesian
updating, seeded discrete simulation, and a durable forecast/outcome ledger.
It has no production API, natural-language compiler, general mathematical
solver, full backtesting, or PRIME integration. No production source, image,
database, identity, or service was changed.
