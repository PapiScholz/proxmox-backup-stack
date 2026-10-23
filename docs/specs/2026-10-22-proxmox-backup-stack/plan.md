# Implementation Plan: proxmox-backup-stack

## Overview

Construir el repo IaC completo (Ansible + bootstrap bash + CI + docs) que despliega
el stack de backups Proxmox descrito en `spec.md`. Se construye de abajo hacia
arriba: primero el andamiaje y la pieza-hoja reusable (dashboard), después los 4
roles en orden de dependencia, y al final la orquestación, el CI y la publicación.

## Architecture Decisions

- **Ansible corre como root en los nodos del cluster** (control node = un nodo PVE,
  conexión `local` + SSH al resto). Por eso los objetos PVE/PBS se crean con sus
  **CLIs nativas** (`pvesh`, `pvesm`, `proxmox-backup-manager`, `pveum`) vía
  `ansible.builtin.command` idempotente — **no** hace falta bootstrappear un token
  de API para que Ansible funcione. Evita el huevo-y-la-gallina y es más simple.
- **Idempotencia hand-rolled**: cada `command` chequea existencia antes de crear
  (`changed_when`/`failed_when` sobre "already exists"), porque no hay módulos
  nativos para datastore PBS / storage PBS / backup job.
- **El CT del dashboard** se crea con `pct create` (guarda: `pct status <id>`),
  igual que el resto de los objetos por CLI nativa. Descartado
  `community.general.proxmox`: pide credenciales de API (user/password o token),
  justo lo que la decisión anterior evita. Su app se instala con tareas
  `copy`+`template`+`systemd`.
- **Los tokens read-only del dashboard** (PVE PVEAuditor, PBS DatastoreAudit) se
  generan con CLI y su valor se guarda solo en el `collector.py` del CT, nunca en
  el repo.
- **Dashboard como pieza-hoja**: `dashboard/` (collector + units) es la fuente
  única; tanto el rol `backup_dashboard` como `scripts/bootstrap-dashboard.sh` la
  consumen. Un solo lugar para mantener.
- **TLS self-signed en LAN**: el colector no verifica cert (documentado); se ofrece
  pin de fingerprint como variable opcional.
- **Público/open-source**: todos los valores reales salen a `*.example`; IPs de
  documentación RFC 5737 (`192.0.2.0/24`, `198.51.100.0/24`); `.gitignore` bloquea
  los archivos reales.

## Dependency Graph

```
scaffolding (meta, ansible.cfg, inventory.example, group_vars.example)
    │
    ├── dashboard/ (collector.py + units)        [pieza-hoja reusable]
    │       ├── role: backup_dashboard
    │       └── scripts/bootstrap-dashboard.sh
    │
    └── roles del stack (orden estricto):
          pbs_datastore_nas → pve_pbs_storage → pve_backup_job → backup_dashboard
                    │
                    └── site.yml (orquesta todo con tags)
                              │
                              ├── .github/workflows/lint.yml (CI)
                              └── README.md + ARCHITECTURE.md
                                        │
                                        └── publicación (git init + push)  [gated]
```

## Task List

### Phase 1: Foundation
- [x] Task 1: Andamiaje y meta del repo
- [x] Task 2: Inventario de ejemplo + variables de ejemplo

### Checkpoint: Foundation
- [x] `ansible-inventory -i inventory.example.ini --list` parsea sin error
- [x] `group_vars/all.example.yml` carga como YAML válido

### Phase 2: Dashboard (pieza-hoja reusable)
- [x] Task 3: Generalizar `dashboard/collector.py` + units systemd
- [x] Task 4: `scripts/bootstrap-dashboard.sh` + `dashboard.env.example`

### Checkpoint: Dashboard
- [x] `python3 -m py_compile dashboard/collector.py` ok
- [x] `shellcheck scripts/bootstrap-dashboard.sh` limpio

### Phase 3: Roles del stack (orden de dependencia)
- [x] Task 5: Role `pbs_datastore_nas`
- [x] Task 6: Role `pve_pbs_storage`
- [x] Task 7: Role `pve_backup_job`
- [x] Task 8: Role `backup_dashboard`

### Checkpoint: Roles
- [x] `ansible-lint roles/` limpio
- [x] cada rol tiene `defaults/main.yml` con todas sus variables

### Phase 4: Orquestación, CI y docs
- [x] Task 9: `site.yml` con plays por grupo y tags
- [x] Task 10: `.github/workflows/lint.yml` (ansible-lint + shellcheck)
- [x] Task 11: `README.md` (quickstart) + `ARCHITECTURE.md` + checklist runtime
- [x] Task 12: Pasada de validación local y fixes

### Checkpoint: Complete
- [x] `ansible-playbook site.yml --syntax-check` pasa
- [x] README quickstart coincide con los comandos reales
- [x] No hay ningún valor real/secreto en el árbol (grep de IPs del lab = 0)

### Phase 5: Publicación (deployment — requiere tu OK explícito)
- [ ] Task 13: `git init` + commit inicial + crear repo público + `git push`

## Risks and Mitigations

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Fuga de topología/secretos al repo público | Alto | `.gitignore` de los reales; solo `*.example` con RFC 5737; Task 12 hace grep de verificación antes de publicar |
| `community.general` no instalado / versión | Medio | `requirements.yml` + documentar `ansible-galaxy collection install`; roles del stack usan CLI, no módulos |
| No puedo correr ansible-lint/shellcheck en Windows | Medio | CI es la fuente de verdad; validación local best-effort (py_compile, yaml load) |
| Privilege-separation de tokens PBS (permiso = intersección user∩token) | Medio | el rol da ACL al **usuario y al token**; documentado |
| Bind-mount/idmap en PBS unprivileged | Medio | rol edita fstab del host + `.conf` del CT con guardas idempotentes; prereqs del NFS documentados |
| Un `command` no-idempotente duplica objetos | Medio | chequear-antes-de-crear en todos; checkpoint exige `changed=0` en 2da corrida (manual) |

## Open Questions

(none)

## Notas

- Tareas registradas en `tasks.md` (mismo folder). El build real (Phase 3-4 del
  SDLC) ejecuta las tasks en orden; cada checkpoint se revisa con el humano.
- Phase 5 (publicación) NO se ejecuta sin tu palabra explícita de `push` en el turno.
