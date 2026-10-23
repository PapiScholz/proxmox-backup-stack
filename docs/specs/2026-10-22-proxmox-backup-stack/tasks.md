# Tasks: proxmox-backup-stack

Orden por dependencia. Cada task es S/M (<=5 archivos). `[ ]` abierta, `[x]` hecha.

---

## Task 1: Andamiaje y meta del repo
**Description:** Esqueleto del repo y archivos meta.
**Acceptance:**
- [x] `LICENSE` (MIT), `.gitignore` (bloquea `inventory.ini`, `group_vars/all.yml`, `*.env`, `*.vault`, `*.retry`), `ansible.cfg` (inventory default, `host_key_checking=False` documentado), `requirements.yml` (`community.general`).
**Verify:** `git check-ignore` simulado sobre los paths sensibles; YAML de `requirements.yml` carga.
- 2026-10-23: `requirements.yml` eliminado. `community.general` solo hacia falta para el modulo `proxmox`, reemplazado por `pct create` (Task 8); ningun rol usa colecciones.
**Dependencies:** None. **Files:** `LICENSE`, `.gitignore`, `ansible.cfg`, `requirements.yml`. **Scope:** S

## Task 2: Inventario + variables de ejemplo
**Description:** `inventory.example.ini` (grupos `pve_nodes`, `pbs`, con IPs RFC 5737) y `group_vars/all.example.yml` con TODAS las variables (nodos, NAS export, datastore path/nombre, idmap uid, storage name, schedules, retención, IP/ID del CT dashboard, umbrales OK/warn).
**Acceptance:**
- [x] Toda variable que usan los roles está en el example con valor genérico y comentario.
- [x] Cero IPs/hostnames reales (solo `192.0.2.x` / `198.51.100.x` / `pve1,pbs1`).
**Verify:** `ansible-inventory -i inventory.example.ini --list` parsea; `all.example.yml` carga como YAML.
**Dependencies:** 1. **Files:** `inventory.example.ini`, `group_vars/all.example.yml`. **Scope:** S

## Task 3: Generalizar dashboard (collector + units)
**Description:** Portar `collector.py` + units a `dashboard/`, parametrizando hosts/puertos/store/umbrales por variables de entorno (con defaults), para que sirva igual al rol y al bootstrap.
**Acceptance:**
- [x] `collector.py` lee config de env vars (`PVE_HOST`, `PBS_HOST`, `PBS_STORE`, `OK_HOURS`, `WARN_DAYS`, tokens) con defaults seguros.
- [x] `html.escape` en toda salida; errores de red se muestran en banner, no explotan.
**Verify:** `python3 -m py_compile dashboard/collector.py`.
**Dependencies:** 1. **Files:** `dashboard/collector.py`, `dashboard/backup-dashboard.service`, `dashboard/backup-dashboard.timer`. **Scope:** S

## Task 4: bootstrap-dashboard.sh + env de ejemplo
**Description:** Script bash (`set -euo pipefail`) que instala el dashboard en un Debian fresco: paquetes, copia collector+units, escribe config desde `dashboard.env`, habilita timer y nginx.
**Acceptance:**
- [x] Lee `dashboard.env` (con `dashboard.env.example` versionado), idempotente al re-correr.
- [x] `shellcheck` limpio.
- Probado 2026-10-22 en CT sandbox Debian 13 (unprivileged) en un PVE 9 real: 2 corridas, nginx 200, timer dispara, CA de PVE y PBS validan (tokens falsos: 401 esperado).
**Verify:** `shellcheck scripts/bootstrap-dashboard.sh`; `bash -n` ok.
**Dependencies:** 3. **Files:** `scripts/bootstrap-dashboard.sh`, `dashboard.env.example`. **Scope:** M

## Task 5: Role pbs_datastore_nas
**Description:** NFS en el host PVE del PBS (fstab + mount), bind-mount al CT PBS (`.conf`), `chown` con idmap, `proxmox-backup-manager datastore create` + prune/GC/verify schedules.
**Acceptance:**
- [x] Todas las tareas idempotentes (chequean antes de crear/montar).
- [x] `defaults/main.yml` con export NFS, path, nombre datastore, uid idmap, schedules.
**Verify:** `ansible-lint roles/pbs_datastore_nas`; revisión de guardas de idempotencia.
**Dependencies:** 2. **Files:** `roles/pbs_datastore_nas/{tasks/main.yml,defaults/main.yml,handlers/main.yml}`. **Scope:** M

## Task 6: Role pve_pbs_storage
**Description:** `pvesm add pbs` en el cluster + usuario/token PBS + ACL **DatastoreAdmin al usuario Y al token** (privilege-separation).
- 2026-10-23: default bajado a `DatastoreBackup` (hallazgo de security review). Segun el apidoc de PBS 4.2.8 alcanza para status, backup y listar/restaurar los propios; borrar desde PVE pide `Datastore.Prune` (`DatastorePowerUser`).
**Acceptance:**
- [x] Storage queda `active`; idempotente; ACL en ambos (user y token).
- [x] `defaults/main.yml` con nombre storage, repo PBS, fingerprint, datastore.
**Verify:** `ansible-lint roles/pve_pbs_storage`.
**Dependencies:** 5. **Files:** `roles/pve_pbs_storage/{tasks/main.yml,defaults/main.yml}`. **Scope:** M

## Task 7: Role pve_backup_job
**Description:** Crear/asegurar el job `/cluster/backup` (`--all`, snapshot, storage pbs, `prune-backups keep-all=1`, schedule) idempotente por un id estable o por match de parámetros.
**Acceptance:**
- [x] No duplica el job al re-correr; schedule/retención parametrizables.
**Verify:** `ansible-lint roles/pve_backup_job`.
**Dependencies:** 6. **Files:** `roles/pve_backup_job/{tasks/main.yml,defaults/main.yml}`. **Scope:** S

## Task 8: Role backup_dashboard
**Description:** Crear el CT (community.general.proxmox), instalar python+nginx, copiar `dashboard/`, generar tokens read-only (PVEAuditor + DatastoreAudit), inyectar config, habilitar timer.
**Acceptance:**
- [x] CT idempotente (no recrea si existe, `pct create` + guarda `pct status`); tokens solo en el CT, no en el repo.
- [x] CT con `--features nesting=1`: con Debian 13 (systemd 257) sin nesting, `pct create` avisa y fallan `tmp.mount`/`run-lock.mount`/`dev-mqueue.mount` (visto en sandbox).
- [x] `defaults/main.yml` con id/IP/recursos del CT, umbrales.
**Verify:** `ansible-lint roles/backup_dashboard`.
**Dependencies:** 3, 7. **Files:** `roles/backup_dashboard/{tasks/main.yml,defaults/main.yml,handlers/main.yml}`. **Scope:** M

## Task 9: site.yml
**Description:** Playbook raíz: play sobre `pve_nodes`/`pbs` que incluye los roles en orden, con `tags` (`datastore`,`storage`,`job`,`dashboard`).
**Acceptance:**
- [x] `--syntax-check` pasa; tags permiten correr capas sueltas.
- Un play por rol (no uno solo): `meta: end_host` corta el host para todo el play; con un play unico el dashboard en otro nodo no corria (probado: 0 vs 5 tareas). Grupo `[pbs]` eliminado del inventario: el PBS se opera con `pct exec`.
**Verify:** `ansible-playbook site.yml --syntax-check`.
**Dependencies:** 5,6,7,8. **Files:** `site.yml`. **Scope:** S

## Task 10: CI lint
**Description:** Workflow que corre `ansible-lint` y `shellcheck` en push/PR.
**Acceptance:**
- [x] Workflow YAML válido; instala colección; corre ambos linters. (actionlint ok; pasos replicados en WSL con ansible.cfg activo; gate rojo verificado)
**Verify:** validar el YAML del workflow; (CI real al pushear).
**Dependencies:** 9. **Files:** `.github/workflows/lint.yml`. **Scope:** S

## Task 11: README + ARCHITECTURE + checklist
**Description:** `README.md` con requisitos, quickstart (copiar examples, editar, `ansible-playbook`), y la vía bootstrap; `ARCHITECTURE.md` con diagrama de flujo y checklist de verificación runtime.
**Acceptance:**
- [x] Comandos del README = comandos reales del repo; sin datos del lab.
**Verify:** lectura cruzada contra `site.yml`/scripts.
**Dependencies:** 9,4. **Files:** `README.md`, `docs/ARCHITECTURE.md`. **Scope:** M

## Task 12: Validación local + fixes
**Description:** Correr lo disponible localmente (py_compile, carga YAML, `bash -n`, y `ansible-lint`/`shellcheck` si están) y un **grep de seguridad** por IPs/hostnames del lab.
**Acceptance:**
- [x] Todo lo corrible pasa; grep de topología real = 0 matches.
**Verify:** salidas de los comandos en verde.
**Dependencies:** 1-11. **Files:** (fixes donde haga falta). **Scope:** S

## Checkpoint final (revisar con el humano antes de publicar)
- [x] `--syntax-check` ok, linters ok, grep de seguridad = 0.

## Task 13: Publicación [GATED — requiere "pusheá" explícito tuyo]
**Description:** `git init`, commit inicial, crear repo público en tu GitHub (`gh repo create`), `git push`.
**Acceptance:**
- [x] Repo público creado; push ok; CI corre. (2026-10-23: github.com/PapiScholz/proxmox-backup-stack, run 39896948351 verde)
**Verify:** `gh repo view`; Actions en verde.
**Dependencies:** 12 + autorización explícita. **Files:** (git). **Scope:** S
