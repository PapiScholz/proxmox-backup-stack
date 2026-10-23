#!/usr/bin/env python3
"""Colector del dashboard de backups.

Consulta la API de PVE (guests del cluster) y la de PBS (grupos de backup del
datastore), cruza los datos y escribe un index.html estatico con el estado de
cada guest. Solo stdlib.

Toda la configuracion sale de variables de entorno (ver dashboard.env.example).
Un error de red no aborta: se muestra como banner en la pagina.
"""

import hashlib
import html
import http.client
import json
import os
import ssl
import sys
import tempfile
import time
from datetime import datetime, timezone

SEVERITY = {"sin-backup": 0, "viejo": 1, "atencion": 2, "ok": 3}
LABELS = {"ok": "OK", "atencion": "Atencion", "viejo": "Viejo", "sin-backup": "Sin backup"}


def env(name, default=None):
    value = os.environ.get(name, "").strip()
    return value if value else default


def env_float(name, default):
    try:
        return float(env(name, default))
    except ValueError:
        return float(default)


def load_config():
    return {
        "pve_host": env("PVE_HOST", "127.0.0.1"),
        "pve_port": int(env("PVE_PORT", "8006")),
        "pve_token_id": env("PVE_TOKEN_ID", ""),
        "pve_token_secret": env("PVE_TOKEN_SECRET", ""),
        "pve_fingerprint": env("PVE_FINGERPRINT", ""),
        "pbs_host": env("PBS_HOST", "127.0.0.1"),
        "pbs_port": int(env("PBS_PORT", "8007")),
        "pbs_token_id": env("PBS_TOKEN_ID", ""),
        "pbs_token_secret": env("PBS_TOKEN_SECRET", ""),
        "pbs_fingerprint": env("PBS_FINGERPRINT", ""),
        "pve_ca_file": env("PVE_CA_FILE", ""),
        "pbs_ca_file": env("PBS_CA_FILE", ""),
        "pbs_store": env("PBS_STORE", "backups"),
        "ok_hours": env_float("OK_HOURS", "26"),
        "warn_days": env_float("WARN_DAYS", "3"),
        "refresh_minutes": env_float("REFRESH_MINUTES", "5"),
        "timeout": env_float("HTTP_TIMEOUT", "10"),
        "output": env("OUTPUT", "/var/www/html/index.html"),
    }


def normalize_fp(fp):
    return fp.replace(":", "").strip().lower()


def api_get(host, port, path, auth_header, fingerprint, timeout, ca_file=""):
    """GET a una API Proxmox. Devuelve el campo "data" del JSON.

    Verificacion TLS, de mas a menos estricta:
      - ca_file: valida la cadena contra ese CA (PVE: /etc/pve/pve-root-ca.pem
        copiado al CT; PBS: su proxy.pem, que es self-signed). No chequea hostname: los certs de nodo suelen no
        incluir la IP por la que se los consulta.
      - fingerprint: compara el SHA-256 del cert del servidor.
      - ninguno: no verifica (cert self-signed en una LAN de confianza).
    """
    if ca_file:
        ctx = ssl.create_default_context(cafile=ca_file)
        ctx.check_hostname = False
        # Python >= 3.13 activa VERIFY_X509_STRICT por defecto y el CA raiz de
        # PVE (pve-root-ca.pem) no trae la extension keyUsage: sin esto la
        # cadena falla aunque sea la correcta.
        ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    try:
        conn.connect()
        if fingerprint:
            der = conn.sock.getpeercert(binary_form=True)
            got = hashlib.sha256(der).hexdigest()
            if got != normalize_fp(fingerprint):
                raise RuntimeError("fingerprint TLS no coincide en %s:%s" % (host, port))
        conn.request("GET", path, headers={"Authorization": auth_header})
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != 200:
            raise RuntimeError("HTTP %s en %s:%s%s" % (resp.status, host, port, path))
        return json.loads(body).get("data")
    finally:
        conn.close()


def fetch_guests(cfg):
    auth = "PVEAPIToken=%s=%s" % (cfg["pve_token_id"], cfg["pve_token_secret"])
    data = api_get(cfg["pve_host"], cfg["pve_port"], "/api2/json/cluster/resources?type=vm",
                   auth, cfg["pve_fingerprint"], cfg["timeout"], cfg["pve_ca_file"]) or []
    guests = []
    for item in data:
        if item.get("template"):
            continue
        guests.append({
            "vmid": int(item["vmid"]),
            "name": item.get("name", ""),
            "type": "ct" if item.get("type") == "lxc" else "vm",
            "node": item.get("node", ""),
            "status": item.get("status", ""),
        })
    return guests


def parse_vmids(value):
    """"101,102" / 101 / None -> {101, 102}. La API devuelve null si no hay lista."""
    if value is None:
        return set()
    return {int(v) for v in str(value).split(",") if v.strip()}


def fetch_excluded(cfg):
    """Cobertura de los backup jobs habilitados.

    None = no se puede determinar (p. ej. jobs por pool): no se marca a nadie
    como excluido en vez de dar falsos positivos.
    """
    auth = "PVEAPIToken=%s=%s" % (cfg["pve_token_id"], cfg["pve_token_secret"])
    jobs = api_get(cfg["pve_host"], cfg["pve_port"], "/api2/json/cluster/backup",
                   auth, cfg["pve_fingerprint"], cfg["timeout"], cfg["pve_ca_file"]) or []
    covered_all, excluded_everywhere, explicit = False, None, set()
    for job in jobs:
        if not job.get("enabled", 1):
            continue
        if job.get("pool"):
            return None
        if job.get("all"):
            covered_all = True
            excl = parse_vmids(job.get("exclude"))
            excluded_everywhere = excl if excluded_everywhere is None else excluded_everywhere & excl
        else:
            explicit |= parse_vmids(job.get("vmid"))
    return {"all": covered_all, "excluded": (excluded_everywhere or set()) - explicit,
            "explicit": explicit}


def fetch_last_backups(cfg):
    auth = "PBSAPIToken=%s:%s" % (cfg["pbs_token_id"], cfg["pbs_token_secret"])
    path = "/api2/json/admin/datastore/%s/groups" % cfg["pbs_store"]
    data = api_get(cfg["pbs_host"], cfg["pbs_port"], path, auth,
                   cfg["pbs_fingerprint"], cfg["timeout"], cfg["pbs_ca_file"]) or []
    last = {}
    for group in data:
        if group.get("backup-type") not in ("vm", "ct"):
            continue
        try:
            vmid = int(group.get("backup-id"))
        except (TypeError, ValueError):
            continue
        last[(group["backup-type"], vmid)] = {
            "time": group.get("last-backup"),
            "count": group.get("backup-count", 0),
        }
    return last


def classify(age_hours, cfg):
    if age_hours is None:
        return "sin-backup"
    if age_hours <= cfg["ok_hours"]:
        return "ok"
    if age_hours <= cfg["warn_days"] * 24:
        return "atencion"
    return "viejo"


def human_age(hours):
    if hours is None:
        return "-"
    if hours < 1:
        return "%d min" % max(0, hours * 60)
    if hours < 48:
        return "%.0f h" % hours
    return "%.1f dias" % (hours / 24)


def build_rows(guests, last, coverage, now, cfg):
    rows = []
    for g in guests:
        info = last.get((g["type"], g["vmid"]))
        ts = info["time"] if info else None
        age = (now - ts) / 3600 if ts else None
        state = classify(age, cfg)
        not_covered = coverage is not None and (
            (not coverage["all"] and g["vmid"] not in coverage["explicit"])
            or g["vmid"] in coverage["excluded"])
        rows.append({**g, "age": age, "ts": ts, "count": info["count"] if info else 0,
                     "state": state, "excluded": not_covered})
    rows.sort(key=lambda r: (r["excluded"], SEVERITY[r["state"]], r["vmid"]))
    return rows


def fmt_ts(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def render(rows, errors, cfg, now):
    e = html.escape
    counts = {k: sum(1 for r in rows if r["state"] == k and not r["excluded"]) for k in SEVERITY}
    excluded = sum(1 for r in rows if r["excluded"])
    worst = min((SEVERITY[r["state"]] for r in rows if not r["excluded"]), default=3)
    overall = "err" if errors else {0: "bad", 1: "bad", 2: "warn", 3: "ok"}[worst]

    out = []
    for r in rows:
        state_cls = "skip" if r["excluded"] else r["state"]
        state_txt = "Excluido" if r["excluded"] else LABELS[r["state"]]
        out.append(
            "<tr class='%s'><td class='num'>%d</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td><span class='pill'>%s</span></td><td>%s</td><td>%s</td><td class='num'>%d</td></tr>"
            % (e(state_cls), r["vmid"], e(r["name"]), e(r["type"].upper()), e(r["node"]),
               e(state_txt), e(human_age(r["age"])), e(fmt_ts(r["ts"])), r["count"]))

    banner = "".join("<div class='banner'>%s</div>" % e(msg) for msg in errors)
    generated = datetime.fromtimestamp(now, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    refresh = max(60, int(cfg["refresh_minutes"] * 60))

    return TEMPLATE.format(
        refresh=refresh,
        overall=e(overall),
        banner=banner,
        ok=counts["ok"], warn=counts["atencion"], old=counts["viejo"],
        none=counts["sin-backup"], skip=excluded,
        rows="\n".join(out) or "<tr><td colspan='8'>Sin datos de guests.</td></tr>",
        store=e(cfg["pbs_store"]),
        ok_hours=e("%g" % cfg["ok_hours"]), warn_days=e("%g" % cfg["warn_days"]),
        generated=e(generated),
    )


TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>Backups Proxmox</title>
<style>
:root {{ --bg:#f6f7f9; --fg:#1d232b; --muted:#5d6b7a; --card:#fff; --line:#dfe3e8;
  --ok:#1f7a3f; --warn:#9a6400; --bad:#b3261e; --skip:#6b7280; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#11151a; --fg:#e6e9ed; --muted:#9aa5b1; --card:#1a2027; --line:#2c343d;
    --ok:#4cc27a; --warn:#e3a33b; --bad:#f2776d; --skip:#8b95a1; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px; }}
h1 {{ font-size:22px; margin:0 0 4px; display:flex; align-items:center; gap:10px; }}
.dot {{ width:12px; height:12px; border-radius:50%; display:inline-block; }}
.dot.ok {{ background:var(--ok); }} .dot.warn {{ background:var(--warn); }}
.dot.bad, .dot.err {{ background:var(--bad); }}
.meta {{ color:var(--muted); margin:0 0 18px; }}
.banner {{ background:var(--card); border:1px solid var(--bad); color:var(--bad);
  padding:10px 12px; border-radius:8px; margin:0 0 12px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:10px; margin:0 0 18px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }}
.card b {{ display:block; font-size:24px; }}
.card span {{ color:var(--muted); font-size:13px; }}
.wrap {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:8px; }}
table {{ width:100%; border-collapse:collapse; min-width:720px; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }}
th {{ color:var(--muted); font-weight:600; font-size:13px; }}
tr:last-child td {{ border-bottom:0; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.pill {{ font-weight:600; }}
tr.ok .pill {{ color:var(--ok); }} tr.atencion .pill {{ color:var(--warn); }}
tr.viejo .pill, tr.sin-backup .pill {{ color:var(--bad); }}
tr.skip {{ color:var(--skip); }}
</style>
</head>
<body>
<main>
<h1><span class="dot {overall}"></span>Backups Proxmox</h1>
<p class="meta">Datastore <b>{store}</b> &middot; OK &le; {ok_hours} h &middot; viejo &gt; {warn_days} dias &middot; generado {generated}</p>
{banner}
<div class="cards">
<div class="card"><b>{ok}</b><span>OK</span></div>
<div class="card"><b>{warn}</b><span>Atencion</span></div>
<div class="card"><b>{old}</b><span>Viejos</span></div>
<div class="card"><b>{none}</b><span>Sin backup</span></div>
<div class="card"><b>{skip}</b><span>Excluidos del job</span></div>
</div>
<div class="wrap"><table>
<thead><tr><th class="num">ID</th><th>Nombre</th><th>Tipo</th><th>Nodo</th><th>Estado</th>
<th>Antiguedad</th><th>Ultimo backup</th><th class="num">Snapshots</th></tr></thead>
<tbody>
{rows}
</tbody>
</table></div>
</main>
</body>
</html>
"""


def write_atomic(path, content):
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".index-", suffix=".html")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main():
    cfg = load_config()
    now = time.time()
    errors = []

    if not cfg["pve_token_id"] or not cfg["pbs_token_id"]:
        errors.append("Faltan PVE_TOKEN_ID / PBS_TOKEN_ID en la configuracion.")

    guests, last, coverage = [], {}, None
    try:
        guests = fetch_guests(cfg)
    except Exception as exc:  # noqa: BLE001 - cualquier fallo se muestra, no aborta
        errors.append("PVE: no se pudo leer la lista de guests (%s)." % exc)
    try:
        coverage = fetch_excluded(cfg)
    except Exception as exc:  # noqa: BLE001
        errors.append("PVE: no se pudieron leer los backup jobs (%s)." % exc)
    try:
        last = fetch_last_backups(cfg)
    except Exception as exc:  # noqa: BLE001
        errors.append("PBS: no se pudo leer el datastore %s (%s)." % (cfg["pbs_store"], exc))

    rows = build_rows(guests, last, coverage, now, cfg)
    write_atomic(cfg["output"], render(rows, errors, cfg, now))
    for msg in errors:
        print(msg, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
