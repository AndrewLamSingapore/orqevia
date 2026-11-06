# Storage reclamation decision - HOLD maintenance

No cleanup, trim, compaction, Clean/Purge, disk detach/relocation or shutdown was
performed. Current host free space is ample; all4volumes are active and build
cache is0. Recoverable host space is UNKNOWN, not the16.8GiB accounting gap.

| Mechanism | What it changes | Current decision |
|---|---|---|
| Delete unused images | Removes local image/rollback assets; may free internal ext4 blocks | No deletion authorized for this workstream; older rollback tags already missing |
| Build cache cleanup | Removes build reuse artifacts; does not guarantee host VHDX shrink | Cache0; no benefit, do not run |
| Log rotation | Bounds future log growth at container creation | Prepared10m/3 source policy; live recreation deferred |
| Filesystem discard/fstrim | Tells block layer which filesystem blocks are free; not app deletion | Backend/version support and consequences must be qualified in maintenance; not run |
| VHDX compaction | May reduce allocated virtual-disk file after free blocks are recognized | Offline-only maintenance after verified backup; result not guaranteed |
| Windows disk reclamation | Measured actual increase in host free bytes/NTFS allocation change | Verify before/after, separately from ext4 free or apparent VHDX length |
| Desktop Clean/Purge/reset | Can destroy Docker data/configuration | Not a nondestructive reclamation method; prohibited |

[Docker Desktop4.96.3 release notes](https://docs.docker.com/desktop/release-notes/#4963)
were reviewed alongside actual version4.96.3.244472. They do not establish a
4.96.3 automatic compaction threshold. The older note about temporarily disabled
WSL VHDX compaction belongs to4.59.0; it cannot be applied to this installed
version without current evidence. No automatic compaction guarantee is made.
[Docker WSL guidance](https://docs.docker.com/desktop/features/wsl/) describes
memory reclamation; autoMemoryReclaim concerns RAM, not guaranteed host disk
shrink. Do not change WSL memory/sparse settings to infer storage recovery.

Microsoft's [compact vdisk documentation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/compact-vdisk)
requires a dynamically expanding disk detached or attached read-only. Windows11
is listed; actual Docker-managed disk metadata/state and available tooling must
still be checked. Optimize-VHD/Hyper-V module availability on this Home edition
is unverified; no feature/tool install is warranted now. [WSL disk guidance](https://learn.microsoft.com/en-us/windows/wsl/disk-space)
distinguishes logical disk capacity from occupied host storage.

Priorities: first complete a protected offline backup/recovery qualification,
then apply narrowly scoped Intelligence logging in an approved window. Measure
host allocated/logical and ext4 used values again. Only if host pressure or
verified reclaimable blocks justify it, design a vendor-supported offline discard/
compaction procedure using the exact installed version and verified disk type.
Do not run raw DiskPart, trim or helper images now. Do not delete models/volumes
or rollback resources to make a compaction number look better. Stop on identity,
health, hash or filesystem errors. Keep pre-maintenance disks until recovery is
validated. Expected recovery remains unverified and may be substantially smaller
than the gap, including zero. Recheck authoritative guidance at maintenance time.
