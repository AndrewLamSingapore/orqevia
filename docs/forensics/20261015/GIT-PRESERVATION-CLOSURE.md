# Git preservation cleanup and resumed execution

Owner-directed cleanup and full active-mission resume, 15 October 2026.

## Closed preservation tasks

| Item | Verified outcome | Evidence |
| --- | --- | --- |
| 95 dirty checkout states | All 914 captured files match recorded sizes and SHA-256 hashes. Index/working patches catalogued. Sources remain intact and recoverable. | [Custody receipt](GIT-CUSTODY-CLEANUP.json) |
| 49 unreachable-object packs | Original SHA-256 and pack-trailer checksums match. All packs were indexed and read back by Git in an isolated bare repository. | [Custody receipt](GIT-CUSTODY-CLEANUP.json) |
| Invalid Gitfile | Confirmed 111 zero bytes, matching preserved backup. Reversibly renamed the invalid .git leaf to gitfile.invalid-preserved-20261015.bin inside its existing quarantine directory. | [Quarantine cleanup](INVALID-GITFILE-CLEANUP.json) |
| Three custody-test failures | Byte-preserving archive extraction rerun: 3 PASS. Protected revisions, hashes and oracle code unchanged. | [Formatting closure](WINDOWS-CUSTODY-CLOSURE.json) |

These tasks are closed as preservation/integrity and tooling cleanup. Pack
readback does not establish complete source graph recovery or semantic acceptance
of every historical object. Recorded original missing-parent/source defects remain
historical evidence. No live checkout was reset and no source object was pruned.
The damaged null-filled marker contains no Git-directory pointer to reconstruct.
Its exact bytes remain in both the private backup and reversibly renamed leaf.

## Resume scope

The Owner lifted the execution pause. Resume implementation, checks, authorized
publication and acceptance from existing completed work. Previously owner-parked
historical semantics, optional feeds and further qualifications remain deferred;
this resume does not silently make them release prerequisites.

PR #323 required checks passed and it merged as
4a7528a06fffc616f6cdd00c66119ec9e3429912. The forensic report and prior deployment
evidence are now published through canonical main. The local cleanup/parking
record is carried forward on the current task branch for normal checks and merge.

Current resumed checks found the original deployed Interface source correspondence
intact (17 selected files), trusted Intelligence/God's Eye navigation usable and
the Docker services running. Browser file upload was retried and remains blocked
by the Edge extension file-URL permission. This permission boundary is not bypassed.
Independent Dell assessment and genuine liveness/collector measurements remain
unverified; ABEX retains sole implementation/deployment authority.
