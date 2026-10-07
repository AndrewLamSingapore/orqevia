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

The isolated suite also replays synthetic Owner/Member sessions and artifacts,
then reads them through the **exact accepted Golden Gen 2 PWA source** at
`b171253566e7c879283d2aacf699ae6c1ec8988e`. It checks both roles, device
bindings, Owner-only authority, Member denial, SQLite integrity and artifact
bytes. A negative case proves that a byte-exact replay of an incompatible
candidate schema can silently demote Owner authority; semantic acceptance must
therefore remain a separate, fail-closed gate. This test uses disposable data,
not production identities, secrets, images or volumes.

This is file-byte equivalence, not a live transaction log. A candidate may
write SQLite or artifacts in a format the accepted Golden image cannot read.
Before any live promotion or rollback claim, a bounded trial must establish:

1. A coherent final fence across PRIME and Interface, or a proven complete
   transactional journal. An unfenced file copy is not acceptable.
2. A private, ACL-verified destination, protected manifest-digest pin, exact
   image/config/private-bind identity, and sufficient thermal headroom.
3. Restored **Golden image** and authenticated real Owner/Member semantic
   canaries against a *disposable* replayed volume, plus SQLite integrity and
   artifact content-hash verification. The source-level Golden PWA test above
   is not a container/runtime or real-identity substitute.
4. A fail-closed decision when the candidate and Golden data formats differ.

No production volume, secret, service, image, configuration or Owner identity
is accessed by this rehearsal. This branch remains a candidate, not Golden
rollback acceptance or deployment authorization.
