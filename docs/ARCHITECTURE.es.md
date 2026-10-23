# Arquitectura

[English](ARCHITECTURE.md) | **Español**

## Flujo de un backup

```
                     23:00 backup job (PVE)          01:00 prune     GC / verify
                              |                          |               |
 guests del cluster --vzdump--+--> storage "pbs" --API--> PBS --chunks--> datastore
 (VMs y CTs, --all)              (en todos los nodos)    (CT unprivileged)    |
                                                                         bind-mount
                                                                              |
                                                       nodo PVE: mount NFS <--+
                                                                              |
                                                                         NAS (export)

 CT dashboard --timer--> collector.py --GET read-only--> API PVE (guests, jobs)
                              |                     \--> API PBS (grupos de backup)
                              v
                         index.html --nginx--> http://<ip>/
```

Los backups son incrementales y deduplicados porque los hace el PBS (chunks
content-addressed). La retencion **no** la hace PVE: el job lleva
`prune-backups keep-all=1` y el que poda es el prune job del PBS, seguido del
garbage collection que libera los chunks huerfanos.

## Componentes

| Rol / pieza | Corre en | Que deja |
|---|---|---|
| `pbs_datastore_nas` | `pbs_host_node` | NFS en fstab y montado, `mpN` en el CT del PBS, directorio del datastore con el uid mapeado, datastore, schedule de GC, prune job, verify job |
| `pve_pbs_storage` | `pbs_host_node` | usuario + token en el PBS, `DatastoreBackup` a los dos, storage `pbs` en el cluster con el fingerprint del PBS |
| `pve_backup_job` | `pbs_host_node` | job `/cluster/backup` `--all` con id estable |
| `backup_dashboard` | `dashboard_node` | CT con nesting, python3 + nginx, colector + timer, tokens read-only en PVE y PBS |
| `dashboard/` | dentro del CT | fuente unica del colector y sus units; la usan el rol y `scripts/bootstrap-dashboard.sh` |

## Decisiones

**CLIs nativas en vez de API o modulos.** Ansible corre como root en un nodo
del cluster y usa `pvesh`, `pvesm`, `pveum`, `pct` y `proxmox-backup-manager`.
Asi no hace falta bootstrappear un token de API para que Ansible funcione, y no
hay dependencia de modulos que no cubren datastores, storages PBS ni backup
jobs. El precio es la idempotencia hecha a mano: cada tarea lee el estado
(`--output-format json`) y solo actua si difiere.

**El PBS se opera con `pct exec`.** No necesita SSH propio ni estar en el
inventario. Lo que va del lado PBS en el rol del dashboard se delega a
`pbs_host_node`.

**Un play por rol en `site.yml`.** Cada rol se limita a su nodo con
`meta: end_host`, que termina el host para todo el play. Con los cuatro roles
en un solo play, el primero cortaria al nodo del dashboard si es otro.

**NFS en el host, bind-mount al CT.** Un CT unprivileged no puede montar NFS
(EPERM aunque tenga `features: mount=nfs`). El directorio pertenece a
`pbs_idmap_offset + pbs_backup_uid` (100034 por defecto): el uid 34 del usuario
`backup` del PBS visto desde el host.

**Privilege separation en todos los tokens.** El permiso efectivo de un token
es la interseccion usuario y token, asi que cada rol se asigna a los dos.

**Comparar normalizando defaults.** Las listas de PVE y PBS omiten los campos que
estan en su default (`ignore-verified=true`, `notification-mode=auto`,
`enabled=1`). Los roles los completan antes de comparar; si no, cada corrida
reportaria cambios.

**Secretos separados de la config en el CT del dashboard.** `dashboard.env` se
re-renderiza en cada corrida; los secretos van en `pve-token.env` y
`pbs-token.env` (0600), que solo se escriben al generar un token. Cambiar un
umbral no regenera tokens.

Registradas como ADRs (en inglés): [ADR-0001: Deploy with Ansible driving the native Proxmox CLIs](adr/0001-ansible-with-native-proxmox-clis.md).

## Checklist de verificacion runtime

Despues de `ansible-playbook site.yml`:

- [ ] Re-correr el playbook da `changed=0`.
- [ ] En `pbs_host_node`: `findmnt <nas_mount_point>` muestra el NFS y
      `pct exec <pbs_ct_id> -- findmnt <pbs_ct_mount_point>` el bind-mount.
- [ ] `pct exec <pbs_ct_id> -- proxmox-backup-manager datastore list` incluye el datastore,
      y `prune-job list` / `verify-job list` sus jobs.
- [ ] `pvesm status --storage <pve_pbs_storage_name>` dice `active`.
- [ ] `pvesh get /cluster/backup` muestra el job con `all: 1`, el storage y
      `prune-backups: keep-all=1`.
- [ ] `http://<ip-del-ct-dashboard>/` responde 200, lista los guests y no tiene banner.
- [ ] Despues de la primera corrida del job, los guests pasan a OK en el dashboard.

## Restore

No se automatiza. Desde la GUI de PVE: storage PBS -> Backups -> elegir el
snapshot -> Restore, o con `qmrestore` / `pct restore` apuntando al volumen
`<storage>:backup/...`.
