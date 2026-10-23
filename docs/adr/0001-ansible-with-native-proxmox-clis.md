# ADR-0001: Deploy with Ansible driving the native Proxmox CLIs

- **Status:** accepted
- **Date:** 2026-10-23

## Context

The stack spans objects that live in three places: the PVE cluster (storage,
backup job, users, containers), the PBS (datastore, prune/verify jobs, users,
tokens) and the PVE host that mounts the NAS export. The deploy has to be
idempotent, re-runnable on a cluster that was partly set up by hand, and
publishable as a generic open-source repo with no secrets in it.

Ansible runs as root on a cluster node. From there every object is reachable
with the tools Proxmox itself ships: `pvesh`, `pvesm`, `pveum`, `pct` and, inside
the PBS container through `pct exec`, `proxmox-backup-manager`.

## Decision

Use Ansible with `ansible.builtin` modules only, calling the native Proxmox CLIs
through `command` tasks that read the current state as JSON first and act only
when it differs. A Bash script (`scripts/bootstrap-dashboard.sh`) covers the
dashboard-only install without Ansible.

## Alternatives considered

| Alternative | Why it was discarded |
|---|---|
| Terraform with a Proxmox provider | Providers do not cover PBS datastores, prune/verify jobs or PVE backup jobs |
| `community.general.proxmox` module for the dashboard container | Needs API credentials (user/password or token), which means bootstrapping a token just so Ansible can run; replaced by `pct create` |
| Calling the HTTP APIs from Ansible (`uri`) | Same token-bootstrapping problem, and the CLIs already run as root on the node |
| Plain Bash for the whole stack | Idempotency and dry runs (`--check --diff`) would have to be rebuilt by hand |

## Consequences

- No collections to install and no API token needed to run the playbook.
- Idempotency is hand-made: every role parses CLI JSON output and has to
  normalize fields the CLIs omit when they hold their default value. Breaking
  changes in CLI output formats between Proxmox releases can break a role (e.g.
  `proxmox-backup-manager user generate-token` prints `Result: {json}` and does not
  accept `--output-format`).
- The playbook must run on a PVE node as root; it cannot be driven from an
  arbitrary workstation without SSH as root to the nodes.
- Each role restricts itself to its node with `meta: end_host`, which forces one
  play per role in `site.yml`.

## Sources

- Proxmox VE documentation: https://pve.proxmox.com/pve-docs/
- Proxmox Backup Server documentation: https://pbs.proxmox.com/docs/
- Ansible `command` module: https://docs.ansible.com/ansible/latest/collections/ansible/builtin/command_module.html
