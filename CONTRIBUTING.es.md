# Cómo contribuir

[English](CONTRIBUTING.md) | **Español**

Gracias por sumarte. Son bienvenidos los reportes de bugs, los arreglos y el
soporte para más configuraciones de Proxmox. Al participar aceptás el
[Código de conducta](CODE_OF_CONDUCT.es.md). Los problemas de seguridad van por
el reporte privado, no por issues públicos: ver [SECURITY.es.md](SECURITY.es.md).

## Reportar un bug

Abrí un issue con:

- Versiones de Proxmox VE y PBS (`pveversion`, `proxmox-backup-manager versions`).
- El rol o script involucrado y el comando que corriste.
- La salida de `ansible-playbook site.yml --check --diff` (o la tarea que falla).
- Tus variables con **IPs, hostnames y cualquier secreto reemplazados** por
  valores de ejemplo.

## Antes de abrir un pull request

Corré los mismos chequeos que el CI:

```bash
cp inventory.example.ini inventory.ini
cp group_vars/all.example.yml group_vars/all.yml
ansible-playbook -i inventory.ini site.yml --syntax-check
ansible-lint
shellcheck scripts/*.sh
for f in scripts/*.sh; do bash -n "$f"; done
python3 -m py_compile dashboard/collector.py
```

Si cambiaste un rol, probalo también contra un cluster real, idealmente uno
descartable o un CT que puedas destruir después:

1. Primero `ansible-playbook site.yml --check --diff`, para ver qué cambiaría.
2. Aplicalo.
3. Correlo **otra vez**: la segunda corrida tiene que dar `changed=0`.

En el PR decí en qué versiones de PVE / PBS lo probaste y qué no pudiste probar.

## Reglas del repo

- **Idempotente o no se mergea.** Cada tarea lee el estado actual y solo actúa
  si difiere. La segunda corrida da `changed=0`. Usá `check_mode: false` en los
  comandos de solo lectura para que `--check` siga diciendo algo.
- **Nada destructivo por defecto.** Borrar datos, reiniciar el CT del PBS o rotar
  tokens requiere una variable explícita, en `false` por defecto.
- **Sin datos reales de infraestructura.** Los ejemplos usan IPs de documentación
  (RFC 5737: `192.0.2.0/24`, `198.51.100.0/24`) y nombres genéricos. Nunca
  commitear `inventory.ini`, `group_vars/all.yml` ni `*.env`.
- **Secretos solo con `no_log`.** El valor de un token nunca llega a la salida, al
  repo ni a un archivo fuera del host que lo usa.
- **CLIs nativas, solo `ansible.builtin`.** El porqué está en el
  [ADR-0001](docs/adr/0001-ansible-with-native-proxmox-clis.md). Sumar una
  colección es un cambio de diseño: abrí un issue antes.
- **Una variable nueva** va en el `defaults/main.yml` del rol y, documentada, en
  `group_vars/all.example.yml`.
- **`dashboard/` es compartido** entre el rol y el script de bootstrap: leé
  [dashboard/README.md](dashboard/README.md) antes de tocarlo.
- **Docs en los dos idiomas.** Si cambiás `README.md`, `docs/ARCHITECTURE.md` o
  `SECURITY.md`, actualizá también su `.es.md`, o aclará en el PR que falta
  traducirlo.
- **Sin emojis** en código, docs ni commits.

## Commits y pull requests

- Un tema por pull request; lo chico se revisa más fácil.
- Mensajes de commit en imperativo, explicando el *porqué* cuando no es obvio.
- El CI tiene que estar en verde.
