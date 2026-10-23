# Contributing

**English** | [Español](CONTRIBUTING.es.md)

Thanks for helping. Bug reports, fixes and support for more Proxmox setups are
all welcome. By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
Security issues go through private reporting, not public issues: see
[SECURITY.md](SECURITY.md).

## Reporting a bug

Open an issue with:

- Proxmox VE and PBS versions (`pveversion`, `proxmox-backup-manager versions`).
- The role or script involved and the command you ran.
- The output of `ansible-playbook site.yml --check --diff` (or the failing task).
- Your variables with **IPs, hostnames and anything secret replaced** by
  placeholders.

## Before opening a pull request

Run the same checks as CI:

```bash
cp inventory.example.ini inventory.ini
cp group_vars/all.example.yml group_vars/all.yml
ansible-playbook -i inventory.ini site.yml --syntax-check
ansible-lint
shellcheck scripts/*.sh
for f in scripts/*.sh; do bash -n "$f"; done
python3 -m py_compile dashboard/collector.py
```

If you changed a role, also try it against a real cluster, ideally a disposable
one or a container you can destroy afterwards:

1. `ansible-playbook site.yml --check --diff` first, to see what would change.
2. Apply it.
3. Run it **again**: the second run must report `changed=0`.

Say in the PR which PVE / PBS versions you tested on and what you could not test.

## Rules of the repo

- **Idempotent or it does not merge.** Every task reads the current state and
  acts only if it differs. A second run reports `changed=0`. Use
  `check_mode: false` on read-only commands so `--check` stays meaningful.
- **Nothing destructive by default.** Deleting data, restarting the PBS container
  or rotating tokens needs an explicit opt-in variable, `false` by default.
- **No real infrastructure data.** Examples use documentation IPs (RFC 5737:
  `192.0.2.0/24`, `198.51.100.0/24`) and generic names. Never commit
  `inventory.ini`, `group_vars/all.yml` or `*.env`.
- **Secrets only through `no_log`.** Token values never reach the output, the repo
  or a file outside the host that uses them.
- **Native CLIs, `ansible.builtin` only.** See
  [ADR-0001](docs/adr/0001-ansible-with-native-proxmox-clis.md) for why. Adding a
  collection is a design change: open an issue first.
- **A new variable** goes in the role's `defaults/main.yml` and, documented, in
  `group_vars/all.example.yml`.
- **`dashboard/` is shared** by the role and the bootstrap script: read
  [dashboard/README.md](dashboard/README.md) before changing it.
- **Docs in both languages.** If you change `README.md`, `docs/ARCHITECTURE.md`
  or `SECURITY.md`, update the `.es.md` sibling too, or say in the PR that it
  needs translating.
- **No emojis** in code, docs or commits.

## Commits and pull requests

- One topic per pull request; small is easier to review.
- Commit messages in the imperative, explaining *why* when it is not obvious
  (`Normalize verify-job defaults before comparing`).
- CI must be green.
