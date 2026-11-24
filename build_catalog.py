import csv
import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timezone

from sgp4 import omm
from sgp4.api import Satrec, jday

URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=geo&FORMAT=JSON"
STATUS = {"VERIFIED_ACTIVE", "UNVERIFIED", "INACTIVE"}
POL = {"H", "V", "L", "R"}
BAND = {"Ku", "C", "Ka"}
SIDEREAL = 1.00273791   # dönüş/gün
STALE_DAYS = 365        # bundan eski doğrulama geçersiz sayılır
MIN_SATS = 50           # bunun altında sonuç = bozuk veri, dosya değiştirilmez

errors = []
warnings = []


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def parse_date(text, where):
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except Exception:
        errors.append(f"{where}: tarih YYYY-AA-GG biçiminde olmalı ('{text}')")
        return None


def load_enrich():
    result = {}
    for n, r in enumerate(read_csv("enrich.csv"), start=2):
        sid = (r.get("id") or "").strip()
        where = f"enrich.csv satır {n} ({sid})"
        status = (r.get("status") or "").strip() or "UNVERIFIED"
        if status not in STATUS:
            errors.append(f"{where}: geçersiz status '{status}'")
            continue
        source = (r.get("source") or "").strip()
        verified_on = (r.get("verified_on") or "").strip()
        if status != "UNVERIFIED":
            if not source:
                errors.append(f"{where}: {status} için kaynak (source) zorunlu")
            if not verified_on:
                errors.append(f"{where}: {status} için doğrulama tarihi (verified_on) zorunlu")
        d = parse_date(verified_on, where) if verified_on else None
        if status != "UNVERIFIED" and d is not None and (date.today() - d).days > STALE_DAYS:
            warnings.append(f"{where}: doğrulama {STALE_DAYS} günden eski, 'Doğrulanmadı' sayıldı")
            status = "UNVERIFIED"
        result[sid] = {
            "operator": (r.get("operator") or "").strip() or None,
            "status": status,
            "regions": [x.strip() for x in (r.get("regions") or "").replace(";", "|").split("|") if x.strip()],
            "verified_on": verified_on or None,
            "source": source or None,
        }
    return result


def load_transponders():
    result = {}
    for n, r in enumerate(read_csv("transponders.csv"), start=2):
        sid = (r.get("id") or "").strip()
        where = f"transponders.csv satır {n} ({sid})"
        try:
            freq = int((r.get("freq") or "").strip())
        except ValueError:
            errors.append(f"{where}: freq sayı olmalı")
            continue
        if not 1000 <= freq <= 40000:
            errors.append(f"{where}: freq 1000-40000 MHz dışında")
        pol = (r.get("pol") or "").strip() or None
        band = (r.get("band") or "").strip() or None
        if pol and pol not in POL:
            errors.append(f"{where}: geçersiz pol '{pol}'")
        if band and band not in BAND:
            errors.append(f"{where}: geçersiz band '{band}'")
        sr_text = (r.get("sr") or "").strip()
        sr = None
        if sr_text:
            try:
                sr = int(sr_text)
            except ValueError:
                errors.append(f"{where}: sr sayı olmalı")
        source = (r.get("source") or "").strip()
        if not source:
            errors.append(f"{where}: kaynak (source) zorunlu")
        checked = (r.get("checked_on") or "").strip()
        if not checked:
            errors.append(f"{where}: kontrol tarihi (checked_on) zorunlu")
        else:
            parse_date(checked, where)
        result.setdefault(sid, []).append({
            "freq": freq, "pol": pol, "sr": sr,
            "fec": (r.get("fec") or "").strip() or None,
            "band": band, "source": source or None, "checked_on": checked or None,
        })
    return result


def gmst_deg(jd):
    return (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360.0


def main():
    enrich = load_enrich()
    transponders = load_transponders()

    req = urllib.request.Request(URL, headers={"User-Agent": "ProSatFinder-catalog-builder"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if not isinstance(data, list):
        sys.exit("CelesTrak beklenmeyen veri döndürdü")

    now = datetime.now(timezone.utc)
    jd, fr = jday(now.year, now.month, now.day, now.hour, now.minute, now.second)

    sats = []
    seen = set()
    for f in data:
        try:
            sat = Satrec()
            omm.initialize(sat, f)
            err, pos, _ = sat.sgp4(jd, fr)
            n = float(f["MEAN_MOTION"])
            inc = float(f["INCLINATION"])
            ecc = float(f["ECCENTRICITY"])
        except Exception:
            continue
        if err != 0:
            continue
        drift = abs(n - SIDEREAL) * 360.0
        if ecc > 0.05 or inc > 15 or drift > 0.25:
            continue
        lon = math.degrees(math.atan2(pos[1], pos[0])) - gmst_deg(jd + fr)
        lon = (lon + 180) % 360 - 180
        sid = f"norad-{f['NORAD_CAT_ID']}"
        seen.add(sid)
        e = enrich.get(sid, {})
        obj = {
            "id": sid,
            "name": f["OBJECT_NAME"],
            "operator": e.get("operator"),
            "position": round(lon, 1),
            "status": e.get("status", "UNVERIFIED"),
            "regions": e.get("regions", []),
            "transponders": [
                {k: t[k] for k in ("freq", "pol", "sr", "fec", "band")}
                for t in transponders.get(sid, [])
            ],
            "epoch": f.get("EPOCH"),
        }
        if e.get("verified_on"):
            obj["verified_on"] = e["verified_on"]
            obj["source"] = e["source"]
        sats.append(obj)

    for sid in sorted(set(enrich) | set(transponders)):
        if sid not in seen:
            warnings.append(f"{sid}: güncel CelesTrak GEO listesinde yok, atlandı")

    if errors:
        sys.exit("HATA:\n" + "\n".join(errors))
    if len(sats) < MIN_SATS:
        sys.exit(f"Yalnızca {len(sats)} uydu üretildi (en az {MIN_SATS} beklenir). catalog.json değiştirilmedi.")

    sats.sort(key=lambda s: (s["position"], s["name"]))
    catalog = {
        "meta": {
            "version": int(now.strftime("%Y%m%d")),
            "source": "CelesTrak GEO yörünge verisi + elle doğrulanmış kayıtlar",
            "date": now.strftime("%Y-%m-%d"),
        },
        "satellites": sats,
    }
    with open("catalog.json", "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=1)

    verified = sum(1 for s in sats if s["status"] == "VERIFIED_ACTIVE")
    print(f"{len(sats)} uydu yazıldı, {verified} tanesi doğrulanmış aktif, "
          f"{sum(len(s['transponders']) for s in sats)} transponder.")
    for w in warnings:
        print("UYARI:", w)


if __name__ == "__main__":
    main()
