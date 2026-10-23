# proxmox-backup-stack

**English** | [Español](README.es.md)

Deploys an end-to-end backup system for a **Proxmox VE** cluster backed by a
**Proxmox Backup Server** whose datastore lives on a **NAS over NFS**, plus an
**HTML dashboard** that shows at a glance which guest is missing a backup.

```
NAS (NFS) --mount--> PVE node --bind-mount--> PBS container (datastore)
                                                  ^
PVE cluster --pbs storage + backup job --all------+
                                                  |
dashboard CT --read-only API (PVE + PBS)----------+--> http://<ct-ip>/
```

Deduplicated, incremental backups (done by PBS), retention and verification
scheduled on the PBS, and a PVE job that backs up every guest every night.
Everything is idempotent: re-running the playbook neither breaks nor duplicates
anything.

Details on every piece and on the design decisions in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

- A **PVE 8.x / 9.x** cluster and a **PBS 3.x / 4.x** running as an
  **unprivileged container** on one of its nodes.
- A **NAS with an NFS export** for the datastore, without `root_squash` (the role
  `chown`s it to the mapped uid of the PBS `backup` user). This repo does not
  configure the NAS.
- On the PVE node you run it from: **Ansible core >= 2.15** and root SSH to the
  other cluster nodes.
- For the dashboard: a Debian container template (the role downloads it with
  `pveam` if missing) and a free IP or DHCP.

## Install with Ansible (full stack)

On a PVE node, as root:

```bash
git clone https://github.com/PapiScholz/proxmox-backup-stack.git
cd proxmox-backup-stack

cp inventory.example.ini inventory.ini
cp group_vars/all.example.yml group_vars/all.yml
# edit both: nodes, NAS, datastore, retention, dashboard container

ansible-playbook site.yml --check --diff   # dry run: applies nothing
ansible-playbook site.yml                  # apply
```

Each layer has its own tag, to run it alone:

```bash
ansible-playbook site.yml --tags datastore   # NFS + bind-mount + datastore + prune/GC/verify
ansible-playbook site.yml --tags storage     # PBS user/token + pbs storage on the cluster
ansible-playbook site.yml --tags job         # vzdump --all backup job
ansible-playbook site.yml --tags dashboard   # container + collector + nginx + read-only tokens
```

`inventory.ini` and `group_vars/all.yml` are in `.gitignore`: your topology
never ends up in a commit.

### If part of the stack is already set up by hand

The playbook reads the current state before touching anything and adopts what
already exists:

- **Datastore, prune and verify jobs**: compared against the variables; only
  what differs gets updated. If the datastore sits at the root of the NFS
  export, set `pbs_datastore_path` equal to `pbs_ct_mount_point`.
- **Backup job**: if there is already an `--all` job to the same storage, the
  role does not create another one (that would duplicate every backup): it
  fails and tells you which id to put in `pve_backup_job_id` to adopt it.
- **PBS storage**: if it already exists with a different user, the role fails
  instead of overwriting it.
- **ACLs**: the role only adds the roles it needs; it never removes existing
  ones. If your token already has a broader role (e.g. `DatastoreAdmin`), drop it
  by hand on the PBS:
  `proxmox-backup-manager acl update /datastore/<store> DatastoreAdmin --auth-id '<user>!<token>' --delete true`
  (and the same for `<user>`).
- **Tokens**: a token secret is only shown when the token is created. If the
  token exists but the storage does not, the role stops;
  `-e pbs_regenerate_token=true` regenerates it (invalidating the old one).

Running with `--check --diff` first shows exactly what would change.

## Dashboard only, without Ansible

Inside a fresh Debian (container or VM), as root:

```bash
git clone https://github.com/PapiScholz/proxmox-backup-stack.git
cd proxmox-backup-stack
cp dashboard.env.example dashboard.env
# fill in the hosts and the two read-only tokens (see below)
bash scripts/bootstrap-dashboard.sh
```

It installs python3 + nginx, the collector and a systemd timer, and serves the
page at `http://<ip>/`. Re-running it is safe.

The tokens must be **read-only**:

```bash
# On a PVE node: user + token with PVEAuditor on / (to both user and token)
pveum user add dashboard@pve
pveum user token add dashboard@pve collector --privsep 1
pveum acl modify / --roles PVEAuditor --users dashboard@pve
pveum acl modify / --roles PVEAuditor --tokens 'dashboard@pve!collector'

# On the PBS: user + token with DatastoreAudit on the datastore
proxmox-backup-manager user create dashboard@pbs
proxmox-backup-manager user generate-token dashboard@pbs collector
proxmox-backup-manager acl update /datastore/<store> DatastoreAudit --auth-id dashboard@pbs
proxmox-backup-manager acl update /datastore/<store> DatastoreAudit --auth-id 'dashboard@pbs!collector'
```

## What the dashboard shows

One row per cluster guest with its latest backup on the PBS. The page itself is
in Spanish:

| Status | Meaning |
|---|---|
| OK | latest backup newer than `dashboard_ok_hours` (26 h by default) |
| Atencion (attention) | between `ok_hours` and `dashboard_warn_days` (3 days) |
| Viejo (stale) | older than `warn_days` |
| Sin backup (none) | the guest has no backup at all in the datastore |
| Excluido (excluded) | no enabled backup job covers it |

If an API does not answer or TLS does not validate, the page shows it in a
banner at the top instead of staying empty. It is regenerated every
`dashboard_refresh_minutes`.

## Security

- **No secrets in the repo.** Tokens are generated at deploy time: the storage
  one is kept by PVE in `/etc/pve/priv/`, and the dashboard ones only inside its
  container, in `0600` files. Ansible handles them with `no_log`.
- **Least privilege.** The dashboard uses tokens with `privsep` and read-only
  roles (`PVEAuditor`, `DatastoreAudit`). The storage token gets
  `DatastoreBackup` on its datastore only: it can back up, list and restore its
  own backups, but not delete them, since pruning is the PBS's job. Set
  `pbs_backup_role: DatastorePowerUser` if you want to delete backups from the
  PVE GUI.
- **TLS.** By default the collector validates against the cluster CA
  (`/etc/pve/pve-root-ca.pem`) and the PBS certificate, both copied into the
  container by the role. Alternative: pin SHA-256 fingerprints
  (`dashboard_pve_fingerprint`, `dashboard_pbs_fingerprint`). With neither it
  does not verify: only for a trusted LAN.
- **Nothing destructive by default.** No role deletes data, restarts the PBS
  container (`pbs_allow_ct_restart`) or rotates tokens without an explicit flag.

## Known issues

- **Creating the datastore over NFS takes 10-25 min** (65536 directories; NFS
  metadata is slow). The role waits up to `pbs_datastore_create_timeout`.
- **An unprivileged container cannot mount NFS itself** (EPERM even with
  `mount=nfs`): that is why NFS is mounted on the host and passed in with a
  bind-mount.
- **Debian 13 in a container needs `nesting=1`** or `tmp.mount` and friends
  fail; the role creates the dashboard container with nesting.
- **A single broken guest turns the `--all` job into "job errors"** (e.g. a
  passthrough disk pointing to a device that no longer exists). Exclude it with
  `pve_backup_exclude`.

## Development

```bash
ansible-lint
ansible-playbook -i inventory.example.ini site.yml --syntax-check   # with group_vars/all.yml copied from the example
shellcheck scripts/*.sh
python3 -m py_compile dashboard/collector.py
```

CI (`.github/workflows/lint.yml`) runs the same on every push and PR.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Decisions (ADRs)](docs/adr/)
- [Security](SECURITY.md)
- [Dashboard sources](dashboard/README.md)
- [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md)

## License

[MIT](LICENSE)
