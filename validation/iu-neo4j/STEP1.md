# Step 1: IU WireGuard verification

Verified on 2026-11-26 at 20:17:42 UTC. The user authorized sudo and confirmed
the duplicate laptop peer was inactive. Both required address-conflict checks
produced no output before setup.

The user ran a reviewed local setup helper with interactive sudo. The only
WireGuard secret configuration is `/etc/wireguard/wg-iu.conf`, owned by root:root
with mode 0600. `wg-iu` has a recent handshake and is enabled at boot. Only
10.66.0.0/24 and 10.2.147.0/24 route through it. The default route and DNS are
unchanged. TCP connectivity to 10.2.147.169:7689 passed and was independently
rechecked. See [the command output](step1-verification.json).

WireGuard tools installed successfully. An unrelated NVIDIA DKMS build for the
pending 7.0.0-31 kernel caused apt to return 100. The running kernel is
6.17.0-23, whose WireGuard module is present. Re-running setup skipped the already
installed tools and completed verification. The pending kernel-package issue
was not repaired by this task.

No remote SSH command, database write, local parking, or application change
was performed in this step. Private keys and passwords are not included here.
