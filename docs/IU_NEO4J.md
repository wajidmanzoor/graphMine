# IU Neo4j connectivity

The IU database is reachable through `wg-iu` at `bolt://10.2.147.169:7689` with
`auth=None`. Its discovery document advertises the wrong Bolt port. Always use
the direct `bolt://` URI and port 7689; never follow the advertised 7687 address.
See [NEO4J_BACKENDS.md](NEO4J_BACKENDS.md) for selection and workspace behavior.

## Server WireGuard setup

Before configuring a fresh server, both commands must produce no output:

```sh
ip route | grep -E '10\.2\.147\.|10\.66\.0\.'
ip addr  | grep -E '10\.2\.147\.|10\.66\.0\.'
```

If they find a conflict, resolve it before continuing. The same peer key is
also on the operator's laptop: its tunnel must be inactive while the server
uses that peer. Do not run this fresh-install precheck as an attempt to reset
an already working tunnel.

Install `wireguard-tools` if missing. Install the operator-supplied configuration
only as `/etc/wireguard/wg-iu.conf`, root:root and mode 0600. Enter its secrets
privately; do not put them in tracked files, terminal command arguments, logs or
screenshots. The configuration must have these non-secret network settings:

```ini
[Interface]
Address = 10.66.0.8/32
# Supply PrivateKey privately in the root-only configuration.

[Peer]
# Supply the operator's peer PublicKey and PresharedKey privately.
Endpoint = 149.165.170.197:51820
AllowedIPs = 10.66.0.0/24, 10.2.147.0/24
PersistentKeepalive = 25
```

Do not add a default route or DNS setting. With operator sudo authorization:

```sh
sudo chown root:root /etc/wireguard/wg-iu.conf
sudo chmod 0600 /etc/wireguard/wg-iu.conf
sudo wg-quick up wg-iu
sudo systemctl enable wg-quick@wg-iu
sudo wg show wg-iu
ip route get 10.2.147.169
ip route show default
nc -vz -w 5 10.2.147.169 7689
```

Check the handshake is recent, only the two intended subnets use `wg-iu`, and
the default route and DNS are unchanged. `wg show` hides private key material;
never publish `wg showconf` or private config contents. The retained Step 1
verification is in `validation/iu-neo4j/`.

The read-only application check is:

```sh
.venv/bin/python scripts/check_iu_neo4j.py
```

It reports route/network reachability, Bolt connectivity on 7689 and `RETURN 1`.
It sends no SSH command. `--wake` explicitly requests the normal wake policy,
which still requires AUTOWAKE and the private password environment variable.

## Remote VM policy

GraphMine authenticates as `exouser@10.2.147.169` and pins this public SSH
fingerprint before password authentication:

`SHA256:/irl3Zjs7PpOCCtWsrt3tZsF65YSIcQFsuyja7Qa+r8`

It refuses any other key. Its only permitted remote command strings are:

```text
sudo systemctl start neo4j
sudo systemctl stop neo4j
sudo systemctl status neo4j
```

No other remote shell commands, files, keys, configuration changes or copies are
allowed. The password comes only from `GRAPHMINE_IU_SSH_PASSWORD` and is passed
to sudo through stdin. Remote output and exception details are not logged or
shown in the UI. Start/stop require `GRAPHMINE_IU_NEO4J_AUTOWAKE=true`.

## Troubleshooting

- **VPN tunnel is down:** check `wg-iu`, its route and handshake on this server,
  and confirm the laptop is not competing for the peer. GraphMine sends no SSH
  command when the network is unreachable.
- **Connection refused:** confirm port 7689. If Neo4j is asleep, an explicit
  user action can start it when AUTOWAKE is enabled. Expect roughly 35–40 seconds
  before Bolt accepts connections; GraphMine times out after 120 seconds.
- **Authentication/configuration error:** use the private configured-source file
  with `auth_disabled: true`, the exact direct IU endpoint, and authorized users.
  A user-created connection cannot disable authentication.
- **Host key mismatch:** stop and have the VM administrator verify the key through
  a trusted channel. Never disable pinning or automatically accept a new key.
- **Repeated start failure:** GraphMine waits five minutes after failed SSH;
  verify the private environment and service with the VM administrator. Do not
  extend the remote command allowlist as a workaround.
- **Local source disappeared:** the active backend is IU. Switch to local through
  the administrator card to restore local datasets and saved work.
