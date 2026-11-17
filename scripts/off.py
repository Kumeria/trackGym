#!/usr/bin/env python3
"""Look up a barcode on Open Food Facts and cache it in foods/foods.json.

  off.py BARCODE [--id ID] [--state crudo|cotto|n/a] [--save] [--refresh]

Without --save it only prints what it found (nothing written).
If the barcode is already in the catalog it is served from cache (no network)
unless --refresh is given.

Rules: never fills in missing values. If kcal or a core macro is missing the
product is NOT saved and the user must provide the label.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import track  # noqa: E402

API = "https://world.openfoodfacts.org/api/v2/product/{}.json"
FIELDS = "product_name,product_name_it,brands,nutriments,quantity"
UA = "trackGym/1.0 (personal diet tracker)"


def fetch(barcode: str) -> dict | None:
    url = API.format(barcode) + "?fields=" + FIELDS
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if data.get("status") != 1:
        return None
    return data["product"]


def map_nutriments(n: dict) -> tuple[dict, list[str]]:
    """OFF nutriments → per100g dict. Returns (values, warnings)."""
    warnings = []

    def g(key):
        v = n.get(key)
        try:
            return None if v in (None, "") else float(v)
        except (TypeError, ValueError):
            return None

    kcal = g("energy-kcal_100g")
    if kcal is None and g("energy-kj_100g") is not None:
        kcal = round(g("energy-kj_100g") / 4.184)
        warnings.append("kcal ricavate da kJ (÷4.184): verificare sull'etichetta")
    sodium = g("sodium_100g")
    if sodium is not None:
        sodium_mg = round(sodium * 1000)
    elif g("salt_100g") is not None:
        sodium_mg = round(g("salt_100g") / 2.5 * 1000)
    else:
        sodium_mg = None
    per100 = {
        "kcal": kcal,
        "protein": g("proteins_100g"),
        "carbs": g("carbohydrates_100g"),
        "fat": g("fat_100g"),
        "fiber": g("fiber_100g"),
        "sugar": g("sugars_100g"),
        "sodium_mg": sodium_mg,
    }
    missing = [k for k in track.CORE if per100[k] is None]
    if missing:
        warnings.append("valori mancanti su OFF: " + ", ".join(missing))
    return per100, warnings


def slug(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[àá]", "a", s); s = re.sub(r"[èé]", "e", s)
    s = re.sub(r"[ìí]", "i", s); s = re.sub(r"[òó]", "o", s); s = re.sub(r"[ùú]", "u", s)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40]


def find_cached(foods: dict, barcode: str) -> str | None:
    for k, v in foods.items():
        if v.get("source") == f"off:{barcode}":
            return k
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="off.py")
    p.add_argument("barcode")
    p.add_argument("--id")
    p.add_argument("--state", choices=track.STATES, default="n/a")
    p.add_argument("--save", action="store_true")
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args(argv)
    if not a.barcode.isdigit():
        print("ERRORE: il barcode deve contenere solo cifre.", file=sys.stderr)
        return 1

    foods = track.load_foods()
    cached = find_cached(foods, a.barcode)
    if cached and not a.refresh:
        f = foods[cached]
        print(f"[cache] {cached}: {f['name']} [{f['state']}]\n"
              f"per 100 g: {track.fmt_values(f['per100g'], track.NUTRIENTS)}")
        return 0

    try:
        prod = fetch(a.barcode)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"ERRORE: Open Food Facts non raggiungibile ({e}). "
              "Usa l'etichetta e `track.py food add`.", file=sys.stderr)
        return 2
    if prod is None:
        print(f"Barcode {a.barcode} non trovato su Open Food Facts. Serve l'etichetta.",
              file=sys.stderr)
        return 3

    name = prod.get("product_name_it") or prod.get("product_name") or f"Prodotto {a.barcode}"
    brand = (prod.get("brands") or "").split(",")[0].strip()
    full = f"{name} ({brand})" if brand else name
    per100, warnings = map_nutriments(prod.get("nutriments") or {})
    fid = a.id or cached or slug(f"{brand}_{name}" if brand else name)

    print(f"{fid}: {full} [{a.state}] fonte=off:{a.barcode}")
    if prod.get("quantity"):
        print(f"confezione: {prod['quantity']}")
    print(f"per 100 g: {track.fmt_values(per100, track.NUTRIENTS)}")
    for w in warnings:
        print(f"ATTENZIONE: {w}")

    if any(per100[k] is None for k in track.CORE):
        print("NON salvato: dati incompleti, serve l'etichetta.", file=sys.stderr)
        return 4
    if a.save:
        if fid in foods and foods[fid].get("source") != f"off:{a.barcode}" and not a.refresh:
            print(f"ERRORE: id '{fid}' già usato da un altro alimento; passa --id.",
                  file=sys.stderr)
            return 1
        foods[fid] = {"name": full, "state": a.state, "source": f"off:{a.barcode}",
                      "per100g": per100, "aliases": [], "added": track.today().isoformat()}
        if warnings:
            foods[fid]["note"] = "; ".join(warnings)
        track.save_foods(foods)
        print(f"Salvato '{fid}' nel catalogo.")
    else:
        print("(anteprima: aggiungi --save per salvarlo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
