# dashboard/

Single source of the backup dashboard: `collector.py` plus its systemd units.
Two installers consume these files as they are, so a change here ships through
both:

- `roles/backup_dashboard` copies them into the container with `pct push`.
- `scripts/bootstrap-dashboard.sh` installs them without Ansible.

Rules:

- `collector.py` stays **standard library only**: neither installer runs pip.
- All configuration comes from environment variables. A new variable needs a
  line in `dashboard.env.example` and in `roles/backup_dashboard/templates/dashboard.env.j2`.
- `backup-dashboard.service` reads `dashboard.env` (required) and
  `pve-token.env` / `pbs-token.env` (optional, `EnvironmentFile=-`). The bootstrap
  writes everything to the first file; the role keeps secrets in the other two.
- No end-of-line comments in env files: systemd `EnvironmentFile` treats them
  as part of the value.
