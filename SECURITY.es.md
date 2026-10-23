# Seguridad

[English](SECURITY.md) | **Español**

## Cómo reportar una vulnerabilidad

Usá el reporte privado de GitHub: pestaña **Security** de este repositorio ->
**Report a vulnerability**. Incluí el archivo o rol afectado, las versiones de
Proxmox VE / PBS, los pasos para reproducirlo y el impacto que ves.

No abras issues públicos con vulnerabilidades. Es un proyecto personal mantenido
según disponibilidad: esperá una primera respuesta en unos días.

## Datos que maneja el sistema

| Dato | Clasificación | Dónde se guarda | Quién accede |
|---|---|---|---|
| Backups de los guests (discos y configs de VMs/CTs) | Confidencial (lo que contengan los guests) | Datastore del PBS sobre el export del NAS | root en el host PVE y en el PBS; el token del storage de PVE (`DatastoreAdmin` sobre ese datastore) |
| Nombres de guests, VMIDs, nodos y fechas de backup | Interno | En el `index.html` del dashboard | Cualquiera que llegue al CT del dashboard por el puerto 80 (sin autenticación) |
| Topología del cluster (IPs de nodos, export del NAS, nombres de storage) | Interno | Tu `inventory.ini` y `group_vars/all.yml`, ambos ignorados por git | Quien corre el playbook |

El dashboard **no tiene login**: exponelo solo en una red de confianza.

## Secretos

| Secreto | Dónde vive | Rotación | Responsable |
|---|---|---|---|
| Token del PBS con el que PVE escribe los backups (`pbs_backup_user!pbs_backup_token_name`) | Lo guarda PVE en `/etc/pve/priv/storage/` | `ansible-playbook site.yml --tags storage -e pbs_regenerate_token=true` | Admin del cluster |
| Token read-only de PVE del dashboard (`dashboard_pve_user!dashboard_token_name`, `PVEAuditor`) | `/etc/backup-dashboard/pve-token.env` (0600) dentro del CT del dashboard | `--tags dashboard -e dashboard_regenerate_tokens=true` | Admin del cluster |
| Token read-only del PBS del dashboard (`dashboard_pbs_user!dashboard_token_name`, `DatastoreAudit`) | `/etc/backup-dashboard/pbs-token.env` (0600) dentro del CT del dashboard | igual que el anterior | Admin del cluster |
| Tokens de la instalación sin Ansible | `dashboard.env` (ignorado por git), copiado a `/etc/backup-dashboard/dashboard.env` (0600) | Recrear los tokens en PVE/PBS y volver a correr el bootstrap | Quien lo instala |

- Nunca commitear `inventory.ini`, `group_vars/all.yml`, `dashboard.env` ni
  ningún `*.env` / vault: `.gitignore` los bloquea; el repo solo trae archivos
  `*.example` con IPs de documentación (RFC 5737).
- Ansible maneja los secretos de los tokens con `no_log`; nunca se imprimen.
- Ante una filtración: regenerar con los flags de arriba (invalida el anterior),
  revisar los logs de tareas de PVE y PBS por accesos inesperados, y revisar el
  datastore por snapshots o borrados inesperados.

## Dependencias

Ninguna colección de Ansible y ningún paquete de Python fuera de la biblioteca
estándar. El CI fija `ansible-core` 2.17.x y `ansible-lint` 24.12.2; las GitHub
Actions están fijadas a versión mayor (`actions/checkout@v4`,
`actions/setup-python@v5`). Las actualizaciones son manuales.
