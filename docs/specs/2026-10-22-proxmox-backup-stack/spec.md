# Spec: proxmox-backup-stack

Phase: development
Status: approved

## Objective

Un repo de Infrastructure-as-Code, open-source y genérico, que despliega de punta
a punta un sistema de backups para un cluster **Proxmox VE (PVE)** respaldado por
un **Proxmox Backup Server (PBS)** cuyo datastore vive sobre un **NAS por NFS**, y
que agrega un **watchdog con dashboard HTML** para ver el estado de los backups de
un vistazo.

**Problema que resuelve.** Montar este sistema a mano tiene muchos pasos frágiles
(NFS + bind-mount con idmap en un PBS unprivileged, privilege-separation de tokens
PBS, un backup job `--all` que un solo guest roto tira abajo, y ninguna visibilidad
hasta que alguien mira). Este repo lo vuelve reproducible, versionado e instalable
en pocos pasos en cualquier Proxmox.

**Usuario.** Un homelabber o sysadmin con un cluster PVE + un PBS + un NAS, que
quiere un backup deduplicado, incremental, con retención y verificación, y una
página local que le avise si algún guest se quedó sin respaldo.

**Éxito.** Desde un checkout limpio, editar un archivo de variables y correr un
playbook (o un script) deja el sistema funcionando y el dashboard mostrando verde,
sin pasos manuales ocultos, y re-ejecutable sin romper nada.

**No-objetivos.** No gestiona el hardware del NAS ni su export NFS (lo asume
existente y documenta el requisito); no reemplaza la UI del PBS; no hace
restore/DR automático (se documenta, no se automatiza); no instala el PBS ni el
cluster PVE en sí.

## Tech Stack

- **Ansible** (core >= 2.15), solo `ansible.builtin`: todos los objetos PVE/PBS
  (incluido el CT del dashboard, con `pct create`) vía `command` idempotente
  sobre las CLIs nativas. Nodo de control = un nodo del cluster PVE (conexión
  `local` + SSH a los otros nodos; el PBS se opera con `pct exec`).
  (Originalmente `community.general` para el módulo `proxmox`; se descartó en
  Task 8 porque pide credenciales de API.)
- **Python 3** (solo stdlib) para el colector del dashboard.
- **nginx** (default site de Debian) sirviendo HTML estático; **systemd timer**
  para el colector; **bash** para el bootstrap.
- Objetivo de plataforma: PVE 8.x, PBS 3.x/4.x, template de CT Debian 12/13.

## Commands

```
# Lint / estático
ansible-lint
shellcheck scripts/*.sh

# Validación sin tocar nada
ansible-playbook site.yml --syntax-check
ansible-playbook -i inventory.ini site.yml --check --diff

# Deploy completo (stack)
ansible-playbook -i inventory.ini site.yml

# Solo una capa (tags)
ansible-playbook -i inventory.ini site.yml --tags dashboard
ansible-playbook -i inventory.ini site.yml --tags datastore,storage,job

# Vía rápida solo-dashboard, sin Ansible (corrido dentro de un Debian fresco)
bash scripts/bootstrap-dashboard.sh   # lee variables de ./dashboard.env
```

## Project Structure

```
proxmox-backup-stack/
  README.md                       # quickstart + requisitos + diagrama
  LICENSE                         # MIT
  .gitignore                      # ignora inventory.ini, group_vars/all.yml, *.env, vault
  ansible.cfg
  inventory.example.ini           # nodos PVE + PBS (placeholders)
  group_vars/all.example.yml      # TODAS las variables con valores de ejemplo genericos
  site.yml                        # orquesta los roles en orden
  roles/
    pbs_datastore_nas/            # NFS en host + bind-mount al CT PBS + idmap + datastore.cfg + prune/gc/verify
    pve_pbs_storage/              # storage tipo pbs en los nodos + usuario/token + ACL (user y token)
    pve_backup_job/               # job vzdump --all con retencion delegada al PBS
    backup_dashboard/             # crea el CT, instala colector + nginx + timer, tokens read-only
  dashboard/
    collector.py                  # consulta PBS+PVE, genera index.html (stdlib)
    backup-dashboard.service
    backup-dashboard.timer
  scripts/
    bootstrap-dashboard.sh        # instala SOLO el dashboard sin Ansible
  .github/workflows/lint.yml      # ansible-lint + shellcheck en push/PR
  docs/
    specs/<date>-proxmox-backup-stack/spec.md
    ARCHITECTURE.md               # como encaja todo + diagrama de flujo
```

## Code Style

- **YAML/Ansible**: tareas con `name:` descriptivo, FQCN (`ansible.builtin.*`),
  idempotencia explícita (`creates:`, `changed_when`, chequear-antes-de-crear),
  variables en `group_vars` nunca hardcodeadas en tareas.

```yaml
- name: Crear datastore PBS si no existe
  ansible.builtin.command:
    cmd: "proxmox-backup-manager datastore create {{ pbs_datastore }} {{ pbs_datastore_path }}"
  register: ds_create
  changed_when: "'already exists' not in ds_create.stderr"
  failed_when: ds_create.rc != 0 and 'already exists' not in ds_create.stderr
```

- **Python**: stdlib only, sin dependencias, funciones chicas, `html.escape` en
  toda salida, fallo de red se muestra en la página (no explota el colector).
- **Bash**: `set -euo pipefail`, variables desde un `.env`, `shellcheck`-clean.
- **Sin emojis** en código, docs ni commits. Estado con `[x]`/`[ ]`.

## Testing Strategy

IaC: no hay "unit test" de un backup real; la verificación es por capas.

- **Estático**: `ansible-lint` y `shellcheck` (en CI, sobre push/PR).
- **Sintaxis**: `ansible-playbook --syntax-check`.
- **Dry-run**: `--check --diff` documentado como paso previo a aplicar.
- **Idempotencia**: segunda corrida reporta `changed=0` en los roles (criterio de CI manual/documentado).
- **Runtime manual**: checklist en README (datastore montado, storage `active`,
  job listado, dashboard responde 200 y muestra guests).

## Boundaries

- **Always**: idempotente; variables genéricas; `html.escape` en el colector;
  `set -euo pipefail` en bash; correr `ansible-lint`/`shellcheck` antes de pushear.
- **Ask first**: agregar dependencias/colecciones; cambiar el esquema de retención
  por defecto; cualquier tarea que borre/reescriba datos.
- **Never**: commitear secretos, IPs/hostnames reales, ni topología del lab del autor;
  automatizar `vzdump restore`, `qm destroy` ni prune destructivo sin flag explícito;
  deshabilitar verificación TLS fuera de una LAN con cert self-signed (y documentarlo).

## Success Criteria

1. Desde un checkout limpio: copiar `inventory.example.ini`→`inventory.ini` y
   `group_vars/all.example.yml`→`group_vars/all.yml`, editar valores, y
   `ansible-playbook -i inventory.ini site.yml` deja el stack operativo.
2. Re-ejecutar el playbook da `changed=0` (idempotente).
3. El storage PBS queda `active` en los nodos y el backup job aparece en
   `/etc/pve/jobs.cfg` con la retención delegada al PBS.
4. El CT del dashboard sirve `http://<ip>/` con 200 y lista cada guest con
   estado OK/atención/viejo/sin-backup y antigüedad del último backup.
5. `scripts/bootstrap-dashboard.sh` instala el dashboard solo, sin Ansible, en un
   Debian fresco leyendo `dashboard.env`.
6. CI (ansible-lint + shellcheck) pasa en verde.
7. El repo no contiene ningún secreto ni dato real de infraestructura (solo
   ejemplos genéricos / IPs de documentación RFC 5737).

## Open Questions

(none)
