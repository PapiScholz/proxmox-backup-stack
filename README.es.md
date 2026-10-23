# proxmox-backup-stack

[English](README.md) | **Español**

Despliega de punta a punta un sistema de backups para un cluster **Proxmox VE**
respaldado por un **Proxmox Backup Server** cuyo datastore vive en un **NAS por
NFS**, y le suma un **dashboard HTML** que muestra de un vistazo que guest se
quedo sin backup.

```
NAS (NFS) --mount--> nodo PVE --bind-mount--> CT del PBS (datastore)
                                                  ^
cluster PVE --storage pbs + backup job --all------+
                                                  |
CT dashboard --API read-only (PVE + PBS)----------+--> http://<ip-del-ct>/
```

Backups deduplicados e incrementales (los hace el PBS), retencion y verificacion
programadas en el PBS, y un job de PVE que respalda todos los guests todas las
noches. Todo idempotente: re-correr el playbook no rompe ni duplica nada.

Detalle de cada pieza y de las decisiones en [docs/ARCHITECTURE.es.md](docs/ARCHITECTURE.es.md).

## Requisitos

- Cluster **PVE 8.x / 9.x** y un **PBS 3.x / 4.x** corriendo como **CT
  unprivileged** en uno de sus nodos.
- Un **NAS con un export NFS** para el datastore, sin `root_squash` (el rol hace
  `chown` al uid mapeado del usuario `backup` del PBS). El repo no configura el NAS.
- En el nodo PVE desde el que se corre: **Ansible core >= 2.15** y SSH como root
  hacia los demas nodos del cluster.
- Para el dashboard: un template de CT Debian (el rol lo descarga con `pveam` si
  falta) y una IP libre o DHCP.

## Instalacion con Ansible (stack completo)

En un nodo PVE, como root:

```bash
git clone https://github.com/PapiScholz/proxmox-backup-stack.git
cd proxmox-backup-stack

cp inventory.example.ini inventory.ini
cp group_vars/all.example.yml group_vars/all.yml
# editar los dos: nodos, NAS, datastore, retencion, CT del dashboard

ansible-playbook site.yml --check --diff   # simular: no aplica nada
ansible-playbook site.yml                  # aplicar
```

Cada capa tiene su tag, para correrla sola:

```bash
ansible-playbook site.yml --tags datastore   # NFS + bind-mount + datastore + prune/GC/verify
ansible-playbook site.yml --tags storage     # usuario/token PBS + storage pbs en el cluster
ansible-playbook site.yml --tags job         # backup job vzdump --all
ansible-playbook site.yml --tags dashboard   # CT + colector + nginx + tokens read-only
```

`inventory.ini` y `group_vars/all.yml` estan en `.gitignore`: tu topologia no
termina en un commit.

### Si ya tenes parte del stack armado a mano

El playbook lee el estado antes de tocar nada y adopta lo que ya existe:

- **Datastore, prune y verify jobs**: se comparan contra las variables y solo se
  actualiza lo que difiere. Si el datastore esta en la raiz del NFS, poner
  `pbs_datastore_path` igual a `pbs_ct_mount_point`.
- **Backup job**: si ya hay un job `--all` hacia el mismo storage, el rol no crea
  otro (duplicaria todos los backups): falla y te dice que id poner en
  `pve_backup_job_id` para adoptarlo.
- **Storage PBS**: si ya existe con otro usuario, el rol falla en vez de pisarlo.
- **Tokens**: el secreto de un token solo se ve al crearlo. Si el token existe
  pero el storage no, el rol se frena; `-e pbs_regenerate_token=true` lo regenera
  (invalida el anterior).

Correr primero con `--check --diff` muestra exactamente que cambiaria.

## Solo el dashboard, sin Ansible

Dentro de un Debian fresco (CT o VM), como root:

```bash
git clone https://github.com/PapiScholz/proxmox-backup-stack.git
cd proxmox-backup-stack
cp dashboard.env.example dashboard.env
# completar hosts y los dos tokens read-only (ver abajo)
bash scripts/bootstrap-dashboard.sh
```

Instala python3 + nginx, el colector y un timer de systemd, y deja la pagina en
`http://<ip>/`. Re-correrlo es seguro.

Los tokens tienen que ser **read-only**:

```bash
# En un nodo PVE: usuario + token con PVEAuditor en / (al usuario y al token)
pveum user add dashboard@pve
pveum user token add dashboard@pve collector --privsep 1
pveum acl modify / --roles PVEAuditor --users dashboard@pve
pveum acl modify / --roles PVEAuditor --tokens 'dashboard@pve!collector'

# En el PBS: usuario + token con DatastoreAudit sobre el datastore
proxmox-backup-manager user create dashboard@pbs
proxmox-backup-manager user generate-token dashboard@pbs collector
proxmox-backup-manager acl update /datastore/<store> DatastoreAudit --auth-id dashboard@pbs
proxmox-backup-manager acl update /datastore/<store> DatastoreAudit --auth-id 'dashboard@pbs!collector'
```

## Que muestra el dashboard

Un renglon por guest del cluster con su ultimo backup en el PBS:

| Estado | Significado |
|---|---|
| OK | ultimo backup mas nuevo que `dashboard_ok_hours` (26 h por defecto) |
| Atencion | entre `ok_hours` y `dashboard_warn_days` (3 dias) |
| Viejo | mas viejo que `warn_days` |
| Sin backup | el guest no tiene ningun backup en el datastore |
| Excluido | ningun backup job habilitado lo cubre |

Si una API no responde o el TLS no valida, la pagina lo muestra en un banner
arriba en vez de quedar vacia. Se regenera cada `dashboard_refresh_minutes`.

## Seguridad

- **Sin secretos en el repo.** Los tokens se generan durante el despliegue: el
  del storage queda en `/etc/pve/priv/` (lo guarda PVE) y los del dashboard solo
  dentro de su CT, en archivos `0600`. Ansible los maneja con `no_log`.
- **Minimo privilegio.** El dashboard usa tokens con `privsep` y roles de solo
  lectura (`PVEAuditor`, `DatastoreAudit`). El token del storage tiene
  `DatastoreAdmin` solo sobre su datastore.
- **TLS.** Por defecto el colector valida contra el CA del cluster
  (`/etc/pve/pve-root-ca.pem`) y el cert del PBS, que el rol copia al CT.
  Alternativa: fijar fingerprints SHA-256 (`dashboard_pve_fingerprint`,
  `dashboard_pbs_fingerprint`). Sin ninguno de los dos no verifica: solo para una
  LAN de confianza.
- **Nada destructivo por defecto.** Ningun rol borra datos, ni reinicia el CT del
  PBS (`pbs_allow_ct_restart`), ni rota tokens sin un flag explicito.

## Problemas conocidos

- **Crear el datastore sobre NFS tarda 10-25 min** (65536 directorios; la
  metadata por NFS es lenta). El rol espera hasta `pbs_datastore_create_timeout`.
- **Un CT unprivileged no puede montar NFS adentro** (EPERM aunque tenga
  `mount=nfs`): por eso el NFS se monta en el host y entra por bind-mount.
- **Debian 13 en CT necesita `nesting=1`** o fallan `tmp.mount` y compania; el
  rol crea el CT del dashboard con nesting.
- **Un solo guest roto tira el job `--all` a "job errors"** (p. ej. un disco
  passthrough a un device que ya no existe). Excluirlo con `pve_backup_exclude`.

## Desarrollo

```bash
ansible-lint
ansible-playbook -i inventory.example.ini site.yml --syntax-check   # con group_vars/all.yml copiado del example
shellcheck scripts/*.sh
python3 -m py_compile dashboard/collector.py
```

El CI (`.github/workflows/lint.yml`) corre lo mismo en cada push y PR.

## Documentación

- [Arquitectura](docs/ARCHITECTURE.es.md)
- [Decisiones (ADRs, en inglés)](docs/adr/)
- [Seguridad](SECURITY.es.md)
- [Fuentes del dashboard](dashboard/README.md)
- [Cómo contribuir](CONTRIBUTING.es.md) · [Código de conducta](CODE_OF_CONDUCT.es.md)

## Licencia

[MIT](LICENSE)
