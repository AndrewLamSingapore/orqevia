# Golden post-snapshot delta rehearsal

The 5 October Golden checkpoint proves an isolated restore of one fenced `/data`
snapshot. It does **not** preserve writes accepted after that snapshot.

`scripts.rollback_delta` is an isolated source-level rehearsal for that gap:
given a before snapshot and a later **separately write-fenced** complete data
tree, it packages changed file bytes and deletion tombstones. Replay verifies
the original snapshot, every payload hash, an independently pinned manifest
SHA-256, and exact final file inventory before publishing a new destination.
It never modifies the original snapshot or an existing destination. In tests,
this preserves post-snapshot Owner/Member SQLite rows and artifact bytes and
rejects changed bases, tampered payloads, traversal and occupied destinations.

This is file-byte equivalence, not a live transaction log. A candidate may
write SQLite or artifacts in a format the accepted Golden image cannot read.
Before any live promotion or rollback claim, a bounded trial must establish:

1. A coherent final fence across PRIME and Interface, or a proven complete
   transactional journal. An unfenced file copy is not acceptable.
2. A private, ACL-verified destination, protected manifest-digest pin, exact
   image/config/private-bind identity, and sufficient thermal headroom.
3. Restored Golden application and authenticated Owner/Member semantic canaries
   against a *disposable* replayed volume, plus SQLite integrity and artifact
   content-hash verification. The current source tests do not supply these.
4. A fail-closed decision when the candidate and Golden data formats differ.

No production volume, secret, service, image, configuration or Owner identity
is accessed by this rehearsal. This branch remains a candidate, not Golden
rollback acceptance or deployment authorization.
