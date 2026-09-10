# Using JARVIS

The changes in this candidate are tested development software. They are not yet
installed into your running PRIME. ABEX has not arrived, and production
qualification is still pending. You do not need to install this source package.

**Open JARVIS:** use your existing JARVIS shortcut. After qualified deployment,
Overview will show current work, waiting work, recent recorded completions,
your priorities and anything requiring attention. Advanced / Diagnostics keeps
technical information out of the daily view.

**Check its status:** choose Status in the existing JARVIS menu. The new version
reports what happened, what was handled, what is affected and whether you need
to act. “Runtime checks passed” means those checks passed; it does not mean
the ABEX or action authority has been qualified for production.

**Ask JARVIS:** choose option 8 in the existing JARVIS menu. Enter a calculation,
status question or advisory request such as "Review this architecture". You do
not need to select an agent or model. Unsupported requests are rejected. JARVIS
shows an immediate answer or checks recorded work for a result. A lost response
does not cause another submission. Keep the displayed reference.

Choose V to verify, or 9 for a guarded restart when status is healthy and no work
is pending. These operations retain the existing startup safety checks. The
restart check is an observation, not an atomic system-wide drain; real-host
concurrent submission and restart acceptance remain part of commissioning.

**The Control Surface:** the current screen preserves its existing read-only
conversation and approval-recording limits. The new governed intent service is
implemented for an eventual approved client, but the screen does not yet start
autonomous work. “Check PRIME” and “What needs my attention?” are supported as
read-only requests by that service. Web3 and VELYQUA continuation requests stop
at their missing policy/evidence gates. No work is invented to simulate progress.

**See completed work:** Overview shows recorded completions. Use Evidence to
inspect results and verification. A finished job and a verified useful outcome
are different things.

**Know whether it needs you:** read Anything that needs you. Temporary processing
faults receive bounded retries. If recovery is exhausted, the summary says so.
Do not repeatedly submit the same request or restart PRIME to clear uncertainty.

**After an internet outage:** read-only status and registered exact computations
do not need a cloud model. Local reasoning still needs its local provider and
healthy records. The current pilot has cloud inference disabled. Automatic
Companion reconciliation is not yet implemented because the frozen specifications
have not been materialized.

**If SAFE_STOP appears:** PRIME cannot verify safety for new work. Leave waiting
work in place and ask for a safety review. Do not reset its records or repeatedly
retry. This view reports evidence; it does not itself stop or repair services.

**After an ABEX reboot:** there is no commissioned ABEX yet. Automatic startup and
reboot acceptance will be tested on the actual host before a production handover.
No claim of automatic ABEX recovery is made today.

**Stop or restart safely:** use the established JARVIS Stop operation when a
shutdown is intended; it retains stored data. Reopening the interface does not
restart services. A restart during uncertain work requires the existing recovery
checks. Automatic rollback of authority records is prohibited; never delete
records or restore an old database merely to make a warning disappear.

**Updates:** an engineer prepares and verifies an exact release before promotion.
This candidate is still on production HOLD, so there is no update for you to apply.
