# Security

**English** | [Español](SECURITY.es.md)

## Reporting a vulnerability

Use GitHub's private reporting: **Security** tab of this repository ->
**Report a vulnerability**. Include the affected file or role, the Proxmox
VE / PBS versions, steps to reproduce and the impact you see.

Do not open public issues for vulnerabilities. This is a personal project
maintained on a best-effort basis: expect a first answer within a few days.

## Data the system handles

| Data | Classification | Where it is stored | Who can access it |
|---|---|---|---|
| Guest backups (VM/CT disks and configs) | Confidential (whatever the guests hold) | PBS datastore on the NAS export | root on the PVE host and PBS; the PVE storage token (`DatastoreAdmin` on that datastore) |
| Guest names, VMIDs, nodes and backup timestamps | Internal | Rendered into the dashboard `index.html` | Anyone who can reach the dashboard container on port 80 (no authentication) |
| Cluster topology (node IPs, NAS export, storage names) | Internal | Your `inventory.ini` and `group_vars/all.yml`, both git-ignored | Whoever runs the playbook |

The dashboard has **no login**: expose it only on a trusted network.

## Secrets

| Secret | Where it lives | Rotation | Owner |
|---|---|---|---|
| PBS token used by PVE to write backups (`pbs_backup_user!pbs_backup_token_name`) | Kept by PVE under `/etc/pve/priv/storage/` | `ansible-playbook site.yml --tags storage -e pbs_regenerate_token=true` | Cluster admin |
| Dashboard read-only PVE token (`dashboard_pve_user!dashboard_token_name`, `PVEAuditor`) | `/etc/backup-dashboard/pve-token.env` (0600) inside the dashboard container | `--tags dashboard -e dashboard_regenerate_tokens=true` | Cluster admin |
| Dashboard read-only PBS token (`dashboard_pbs_user!dashboard_token_name`, `DatastoreAudit`) | `/etc/backup-dashboard/pbs-token.env` (0600) inside the dashboard container | same as above | Cluster admin |
| Tokens for the Ansible-free install | `dashboard.env` (git-ignored), copied to `/etc/backup-dashboard/dashboard.env` (0600) | Recreate the tokens on PVE/PBS and re-run the bootstrap | Whoever installs it |

- Never commit `inventory.ini`, `group_vars/all.yml`, `dashboard.env` or any
  `*.env` / vault file: `.gitignore` blocks them; the repo only ships
  `*.example` files with documentation IPs (RFC 5737).
- Ansible handles token secrets with `no_log`; they are never printed.
- If a secret leaks: regenerate it with the flags above (this invalidates the old
  one), review the PVE and PBS task logs for unexpected access, and check the
  datastore for unexpected snapshots or deletions.

## Dependencies

No Ansible collections and no Python packages beyond the standard library.
CI pins `ansible-core` 2.17.x and `ansible-lint` 24.12.2; GitHub Actions are
pinned to major versions (`actions/checkout@v4`, `actions/setup-python@v5`).
Updates are manual.
