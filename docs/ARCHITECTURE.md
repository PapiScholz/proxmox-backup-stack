# Architecture

**English** | [Español](ARCHITECTURE.es.md)

## How a backup flows

```
                     23:00 backup job (PVE)          01:00 prune     GC / verify
                              |                          |               |
 cluster guests  --vzdump-----+--> "pbs" storage --API--> PBS --chunks--> datastore
 (VMs and CTs, --all)             (on every node)       (unprivileged CT)    |
                                                                         bind-mount
                                                                              |
                                                       PVE node: NFS mount <--+
                                                                              |
                                                                         NAS (export)

 dashboard CT --timer--> collector.py --read-only GET--> PVE API (guests, jobs)
                              |                     \--> PBS API (backup groups)
                              v
                         index.html --nginx--> http://<ip>/
```

Backups are incremental and deduplicated because PBS makes them
(content-addressed chunks). Retention is **not** done by PVE: the job carries
`prune-backups keep-all=1` and pruning is done by the PBS prune job, followed by
garbage collection, which frees orphaned chunks.

## Components

| Role / piece | Runs on | Leaves in place |
|---|---|---|
| `pbs_datastore_nas` | `pbs_host_node` | NFS in fstab and mounted, `mpN` on the PBS container, datastore directory owned by the mapped uid, datastore, GC schedule, prune job, verify job |
| `pve_pbs_storage` | `pbs_host_node` | user + token on the PBS, `DatastoreBackup` to both, `pbs` storage on the cluster with the PBS fingerprint |
| `pve_backup_job` | `pbs_host_node` | `/cluster/backup` `--all` job with a stable id |
| `backup_dashboard` | `dashboard_node` | container with nesting, python3 + nginx, collector + timer, read-only tokens on PVE and PBS |
| `dashboard/` | inside the container | single source for the collector and its units; used by the role and by `scripts/bootstrap-dashboard.sh` |

## Decisions

**Native CLIs instead of the API or modules.** Ansible runs as root on a
cluster node and uses `pvesh`, `pvesm`, `pveum`, `pct` and
`proxmox-backup-manager`. That avoids bootstrapping an API token just so Ansible
can work, and avoids depending on modules that do not cover datastores, PBS
storages or backup jobs. The cost is hand-made idempotency: every task reads the
state (`--output-format json`) and only acts if it differs.

**The PBS is driven through `pct exec`.** It needs no SSH of its own and is not
in the inventory. The PBS side of the dashboard role is delegated to
`pbs_host_node`.

**One play per role in `site.yml`.** Each role limits itself to its node with
`meta: end_host`, which ends the host for the whole play. With all four roles in
a single play, the first one would cut off the dashboard node if it is a
different one.

**NFS on the host, bind-mount into the container.** An unprivileged container
cannot mount NFS (EPERM even with `features: mount=nfs`). The directory belongs
to `pbs_idmap_offset + pbs_backup_uid` (100034 by default): uid 34 of the PBS
`backup` user as seen from the host.

**Privilege separation on every token.** A token's effective permission is the
intersection of user and token, so every role is granted to both.

**Compare after normalizing defaults.** PVE and PBS listings omit fields that are
at their default (`ignore-verified=true`, `notification-mode=auto`,
`enabled=1`). The roles fill them in before comparing; otherwise every run would
report changes.

**Secrets kept apart from config in the dashboard container.** `dashboard.env`
is re-rendered on every run; secrets live in `pve-token.env` and `pbs-token.env`
(0600), written only when a token is generated. Changing a threshold does not
regenerate tokens.

Recorded as ADRs: [ADR-0001: Deploy with Ansible driving the native Proxmox CLIs](adr/0001-ansible-with-native-proxmox-clis.md).

## Runtime verification checklist

After `ansible-playbook site.yml`:

- [ ] Re-running the playbook reports `changed=0`.
- [ ] On `pbs_host_node`: `findmnt <nas_mount_point>` shows the NFS and
      `pct exec <pbs_ct_id> -- findmnt <pbs_ct_mount_point>` the bind-mount.
- [ ] `pct exec <pbs_ct_id> -- proxmox-backup-manager datastore list` includes the datastore,
      and `prune-job list` / `verify-job list` its jobs.
- [ ] `pvesm status --storage <pve_pbs_storage_name>` says `active`.
- [ ] `pvesh get /cluster/backup` shows the job with `all: 1`, the storage and
      `prune-backups: keep-all=1`.
- [ ] `http://<dashboard-ct-ip>/` answers 200, lists the guests and has no banner.
- [ ] After the first job run, guests turn OK on the dashboard.

## Restore

Not automated. From the PVE GUI: PBS storage -> Backups -> pick the snapshot ->
Restore, or with `qmrestore` / `pct restore` pointing at the
`<storage>:backup/...` volume.
