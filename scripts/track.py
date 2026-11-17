#!/usr/bin/env python3
"""trackGym — diet tracker CLI.

All nutritional arithmetic lives here. Claude must never compute values by hand.

Commands
  now                                   local time + suggested meal
  add     --meal M (--food ID --grams G | --recipe ID [--portions N]) [--date D] [--note T]
  remove  --meal M --index I [--date D]
  show    [--date D]                    day detail, per-meal totals, remaining
  summary [--date D]                    day totals vs targets
  range   (--from D --to D | --week this|last) [--save]
  food    list | search Q | show ID | add ...

Data root defaults to the repo root; override with TRACKGYM_ROOT (used by tests).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

NUTRIENTS = ["kcal", "protein", "carbs", "fat", "fiber", "sugar", "sodium_mg"]
CORE = ["kcal", "protein", "carbs", "fat"]
OPTIONAL = {"fiber": "fiber", "sugar": "sugar", "sodium": "sodium_mg"}
LABELS = {
    "kcal": "kcal", "protein": "Proteine", "carbs": "Carboidrati", "fat": "Grassi",
    "fiber": "Fibre", "sugar": "Zuccheri", "sodium_mg": "Sodio",
}
UNITS = {"kcal": "", "sodium_mg": " mg"}
MEALS = ["colazione", "pranzo", "cena", "snack"]
STATES = ["crudo", "cotto", "n/a"]


class TrackError(Exception):
    pass


# ---------------------------------------------------------------- paths / io

def root() -> Path:
    env = os.environ.get("TRACKGYM_ROOT")
    return Path(env) if env else Path(__file__).resolve().parent.parent


def foods_path() -> Path:
    return root() / "foods" / "foods.json"


def day_path(date: dt.date) -> Path:
    return root() / "log" / f"{date:%Y}" / f"{date:%m}" / f"{date:%Y-%m-%d}.yaml"


def load_profile() -> dict:
    p = root() / "profile.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def load_foods() -> dict:
    p = foods_path()
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def save_foods(foods: dict) -> None:
    p = foods_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(p.read_text()) if p.exists() else {}
    meta = {k: v for k, v in existing.items() if k.startswith("_")}
    out = {**meta, **dict(sorted(foods.items()))}
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")


def load_day(date: dt.date) -> dict:
    p = day_path(date)
    if p.exists():
        d = yaml.safe_load(p.read_text()) or {}
    else:
        d = {}
    d.setdefault("date", date.isoformat())
    meals = d.get("meals") or {}
    d["meals"] = {m: list(meals.get(m) or []) for m in MEALS}
    return d


def save_day(day: dict, date: dt.date) -> Path:
    p = day_path(date)
    if not any(day["meals"].values()):
        if p.exists():
            p.unlink()
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {"date": date.isoformat(), "meals": {m: day["meals"][m] for m in MEALS if day["meals"][m]}}
    if day.get("notes"):
        out["notes"] = day["notes"]
    p.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True))
    return p


def load_recipe(rid: str) -> dict:
    p = root() / "recipes" / f"{rid}.yaml"
    if not p.exists():
        raise TrackError(f"Ricetta '{rid}' non trovata in recipes/.")
    return yaml.safe_load(p.read_text())


# ---------------------------------------------------------------- time

def tz() -> ZoneInfo:
    return ZoneInfo(load_profile().get("timezone") or "Europe/Rome")


def today() -> dt.date:
    return dt.datetime.now(tz()).date()


def parse_date(s: str | None) -> dt.date:
    if not s or s == "today" or s == "oggi":
        return today()
    if s in ("yesterday", "ieri"):
        return today() - dt.timedelta(days=1)
    return dt.date.fromisoformat(s)


def suggest_meal(t: dt.time) -> str | None:
    """Default slots; None means 'ask the user'."""
    h = t.hour + t.minute / 60
    if 5 <= h < 10.5:
        return "colazione"
    if 11.5 <= h < 15.5:
        return "pranzo"
    if 18.5 <= h < 23:
        return "cena"
    return None


# ---------------------------------------------------------------- math

def r(x: float | None, nutrient: str) -> float | None:
    if x is None:
        return None
    return round(x) if nutrient in ("kcal", "sodium_mg") else round(x, 1)


def compute(per100: dict, grams: float) -> dict:
    """Values for `grams` of a food given its per-100 g values. Missing → None."""
    if grams <= 0:
        raise TrackError("I grammi devono essere > 0.")
    out = {}
    for n in NUTRIENTS:
        v = per100.get(n)
        out[n] = None if v is None else r(v * grams / 100.0, n)
    return out


def total(entries: list[dict]) -> dict:
    """Sum snapshots. Value is None only if no entry has it; `_missing` lists
    nutrients that are unknown for at least one entry (partial total)."""
    tot = {n: None for n in NUTRIENTS}
    missing = set()
    for e in entries:
        vals = e.get("values") or {}
        for n in NUTRIENTS:
            v = vals.get(n)
            if v is None:
                missing.add(n)
            else:
                tot[n] = (tot[n] or 0) + v
    tot = {n: r(v, n) for n, v in tot.items()}
    tot["_missing"] = sorted(missing, key=NUTRIENTS.index)
    return tot


def day_entries(day: dict) -> list[dict]:
    return [e for m in MEALS for e in day["meals"][m]]


def tracked_nutrients(profile: dict) -> list[str]:
    track = profile.get("track") or {}
    return CORE + [OPTIONAL[k] for k in OPTIONAL if track.get(k)]


KCAL_PER_G = {"protein": 4, "carbs": 4, "fat": 9}


def kcal_from_macros(t: dict) -> float | None:
    if any(t.get(m) is None for m in KCAL_PER_G):
        return None
    return r(sum(t[m] * k for m, k in KCAL_PER_G.items()), "kcal")


def targets(profile: dict) -> dict:
    t = profile.get("targets") or {}
    out = {n: t.get(n) for n in NUTRIENTS}
    if t.get("kcal") == "auto":
        out["kcal"] = kcal_from_macros(t)
    return out


def remaining(tot: dict, tgt: dict) -> dict:
    out = {}
    for n in NUTRIENTS:
        if tgt.get(n) is None:
            out[n] = None
        else:
            out[n] = r(tgt[n] - (tot.get(n) or 0), n)
    return out


# ---------------------------------------------------------------- operations

def get_food(foods: dict, fid: str) -> dict:
    if fid not in foods:
        raise TrackError(
            f"Alimento '{fid}' non presente nel catalogo. Serve etichetta o barcode."
        )
    return foods[fid]


def make_entry(fid: str, food: dict, grams: float, note: str | None = None,
               recipe: str | None = None) -> dict:
    e = {
        "food_id": fid,
        "name": food["name"],
        "state": food.get("state", "n/a"),
        "grams": grams if grams != int(grams) else int(grams),
        "values": compute(food["per100g"], grams),
        "source": food.get("source", "manual"),
    }
    if recipe:
        e["recipe"] = recipe
    if note:
        e["note"] = note
    return e


def add_food(date: dt.date, meal: str, fid: str, grams: float, note: str | None = None) -> dict:
    meal = check_meal(meal)
    food = get_food(load_foods(), fid)
    day = load_day(date)
    e = make_entry(fid, food, grams, note)
    day["meals"][meal].append(e)
    save_day(day, date)
    return day


def add_recipe(date: dt.date, meal: str, rid: str, portions: float = 1.0,
               note: str | None = None) -> dict:
    meal = check_meal(meal)
    recipe = load_recipe(rid)
    base = recipe.get("portions", 1) or 1
    factor = portions / base
    foods = load_foods()
    entries = []
    for ing in recipe["ingredients"]:
        food = get_food(foods, ing["food_id"])  # validate everything before writing
        entries.append(make_entry(ing["food_id"], food, round(ing["grams"] * factor, 1),
                                  note, recipe=rid))
    day = load_day(date)
    day["meals"][meal].extend(entries)
    save_day(day, date)
    return day


def remove_entry(date: dt.date, meal: str, index: int) -> dict:
    meal = check_meal(meal)
    day = load_day(date)
    items = day["meals"][meal]
    if not 1 <= index <= len(items):
        raise TrackError(f"Indice {index} non valido per {meal} ({len(items)} voci).")
    removed = items.pop(index - 1)
    save_day(day, date)
    return removed


def check_meal(meal: str) -> str:
    m = meal.lower()
    if m not in MEALS:
        raise TrackError(f"Pasto '{meal}' non valido. Usa: {', '.join(MEALS)}.")
    return m


def range_stats(start: dt.date, end: dt.date) -> dict:
    if end < start:
        raise TrackError("La data finale è precedente a quella iniziale.")
    days = []
    d = start
    while d <= end:
        if day_path(d).exists():
            days.append((d, total(day_entries(load_day(d)))))
        d += dt.timedelta(days=1)
    avg = {}
    for n in NUTRIENTS:
        vals = [t[n] for _, t in days if t[n] is not None]
        avg[n] = r(sum(vals) / len(vals), n) if vals else None
    return {"start": start, "end": end, "days": days, "average": avg,
            "n_days": (end - start).days + 1}


def week_bounds(which: str) -> tuple[dt.date, dt.date]:
    t = today()
    monday = t - dt.timedelta(days=t.weekday())
    if which == "last":
        monday -= dt.timedelta(days=7)
    elif which != "this":
        raise TrackError("--week accetta 'this' o 'last'.")
    return monday, monday + dt.timedelta(days=6)


def solve_fill(foods: dict, fids: list[str], nutrients: list[str], rem: dict) -> dict:
    """Grams of each food so that the listed nutrients exactly match `rem`.
    Square linear system (one food per nutrient), Gaussian elimination."""
    if len(fids) != len(nutrients):
        raise TrackError("Servono tanti alimenti quanti nutrienti da coprire.")
    for n in nutrients:
        if rem.get(n) is None:
            raise TrackError(f"Nessun target impostato per {LABELS[n]}.")
    a = [[(get_food(foods, f)["per100g"].get(n) or 0) / 100.0 for f in fids] + [rem[n]]
         for n in nutrients]
    k = len(fids)
    for c in range(k):
        piv = max(range(c, k), key=lambda i: abs(a[i][c]))
        if abs(a[piv][c]) < 1e-9:
            raise TrackError("Combinazione non risolvibile: alimenti troppo simili per questi nutrienti.")
        a[c], a[piv] = a[piv], a[c]
        for i in range(k):
            if i != c:
                f = a[i][c] / a[c][c]
                a[i] = [x - f * y for x, y in zip(a[i], a[c])]
    grams = {fids[i]: a[i][k] / a[i][i] for i in range(k)}
    neg = [f for f, g in grams.items() if g < 0]
    if neg:
        raise TrackError("Impossibile senza superare il target: con gli altri alimenti " +
                         ", ".join(neg) + " dovrebbe essere negativo.")
    return {f: round(g) for f, g in grams.items()}


# ---------------------------------------------------------------- formatting

def fmt(v, n) -> str:
    if v is None:
        return "n/d"
    s = f"{v:g}" if isinstance(v, float) else str(v)
    return s + UNITS.get(n, " g")


def fmt_values(vals: dict, nutrients: list[str]) -> str:
    parts = []
    for n in nutrients:
        star = "*" if n in vals.get("_missing", []) and vals.get(n) is not None else ""
        parts.append(f"{LABELS[n]} {fmt(vals.get(n), n)}{star}")
    return " | ".join(parts)


def table_vs_targets(tot: dict, profile: dict) -> str:
    tgt = targets(profile)
    rem = remaining(tot, tgt)
    lines = [f"{'':12} {'Totale':>10} {'Target':>10} {'Restano':>10} {'%':>5}"]
    for n in tracked_nutrients(profile):
        pct = ""
        if tgt[n] and tot[n] is not None:
            pct = f"{round(100 * tot[n] / tgt[n])}%"
        star = "*" if n in tot.get("_missing", []) else ""
        lines.append(f"{LABELS[n]:12} {fmt(tot[n], n) + star:>10} {fmt(tgt[n], n):>10} "
                     f"{fmt(rem[n], n):>10} {pct:>5}")
    if any(n in tot.get("_missing", []) for n in tracked_nutrients(profile)):
        lines.append("* totale parziale: dato mancante per almeno un alimento")
    return "\n".join(lines)


def render_day(date: dt.date, profile: dict, only_meal: str | None = None) -> str:
    day = load_day(date)
    nut = tracked_nutrients(profile)
    out = [f"=== {date.isoformat()} ({WEEKDAYS[date.weekday()]}) ==="]
    for m in MEALS:
        items = day["meals"][m]
        if not items or (only_meal and m != only_meal):
            continue
        out.append(f"\n[{m.upper()}]")
        for i, e in enumerate(items, 1):
            tag = f" (ricetta: {e['recipe']})" if e.get("recipe") else ""
            out.append(f"  {i}. {e['name']} [{e['state']}] {e['grams']} g{tag}")
            out.append(f"     {fmt_values(e['values'], nut)}")
        out.append(f"  Totale {m}: {fmt_values(total(items), nut)}")
    if not day_entries(day):
        out.append("\nNessuna voce registrata.")
    out.append("\n" + table_vs_targets(total(day_entries(day)), profile))
    return "\n".join(out)


WEEKDAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def render_range(stats: dict, profile: dict) -> str:
    nut = tracked_nutrients(profile)
    tgt = targets(profile)
    out = [f"# Riepilogo {stats['start']} → {stats['end']}", "",
           f"Giorni registrati: {len(stats['days'])}/{stats['n_days']}", ""]
    head = "| Giorno | " + " | ".join(LABELS[n] for n in nut) + " |"
    out += [head, "|" + "---|" * (len(nut) + 1)]
    for d, t in stats["days"]:
        out.append(f"| {d} {WEEKDAYS[d.weekday()]} | " +
                   " | ".join(fmt(t[n], n) + ("*" if n in t["_missing"] else "") for n in nut) + " |")
    out.append("| **Media** | " + " | ".join(fmt(stats["average"][n], n) for n in nut) + " |")
    out.append("| Target | " + " | ".join(fmt(tgt[n], n) for n in nut) + " |")
    if stats["days"] and tgt.get("kcal"):
        within = sum(1 for _, t in stats["days"]
                     if t["kcal"] is not None and abs(t["kcal"] - tgt["kcal"]) <= 0.1 * tgt["kcal"])
        out += ["", f"Giorni entro ±10% del target kcal: {within}/{len(stats['days'])}"]
    if stats["days"] and tgt.get("protein"):
        hit = sum(1 for _, t in stats["days"]
                  if t["protein"] is not None and t["protein"] >= tgt["protein"])
        out.append(f"Giorni con target proteine raggiunto: {hit}/{len(stats['days'])}")
    return "\n".join(out)


# ---------------------------------------------------------------- food catalog cmds

def food_cmd(args, profile) -> str:
    foods = load_foods()
    if args.fcmd == "list":
        return "\n".join(f"{k:28} {v['name']} [{v.get('state')}] ({v.get('source')})"
                         for k, v in foods.items()) or "Catalogo vuoto."
    if args.fcmd == "search":
        q = args.query.lower()
        hits = {k: v for k, v in foods.items()
                if q in k.lower() or q in v["name"].lower()
                or any(q in a.lower() for a in v.get("aliases", []))}
        return "\n".join(f"{k:28} {v['name']} [{v.get('state')}] ({v.get('source')})"
                         for k, v in hits.items()) or f"Nessun alimento trovato per '{args.query}'."
    if args.fcmd == "show":
        f = get_food(foods, args.id)
        return f"{args.id}: {f['name']} [{f.get('state')}] fonte={f.get('source')}\n" \
               f"per 100 g: {fmt_values(f['per100g'], NUTRIENTS)}"
    if args.fcmd == "add":
        if args.id in foods and not args.force:
            raise TrackError(f"'{args.id}' esiste già. Usa --force per sovrascrivere.")
        if args.source not in ("label", "manual") and not args.source.startswith(("off:", "usda:")):
            raise TrackError("--source deve essere label | manual | off:<barcode> | usda:<fdcId>.")
        per100 = {"kcal": args.kcal, "protein": args.protein, "carbs": args.carbs,
                  "fat": args.fat, "fiber": args.fiber, "sugar": args.sugar,
                  "sodium_mg": args.sodium_mg}
        if args.salt is not None and args.sodium_mg is None:
            per100["sodium_mg"] = round(args.salt / 2.5 * 1000)  # EU labels: salt = sodium × 2.5
        food = {"name": args.name, "state": args.state, "source": args.source,
                "per100g": per100, "aliases": args.alias or [],
                "added": today().isoformat()}
        if args.note:
            food["note"] = args.note
        foods[args.id] = food
        save_foods(foods)
        return f"Salvato '{args.id}'.\nper 100 g: {fmt_values(per100, NUTRIENTS)}"
    raise TrackError("Sottocomando food sconosciuto.")


# ---------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="track.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("now")

    a = sub.add_parser("add")
    a.add_argument("--date")
    a.add_argument("--meal", required=True)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--food")
    g.add_argument("--recipe")
    a.add_argument("--grams", type=float)
    a.add_argument("--portions", type=float, default=1.0)
    a.add_argument("--note")

    rm = sub.add_parser("remove")
    rm.add_argument("--date")
    rm.add_argument("--meal", required=True)
    rm.add_argument("--index", type=int, required=True)

    for name in ("show", "summary"):
        s = sub.add_parser(name)
        s.add_argument("--date")

    rg = sub.add_parser("range")
    rg.add_argument("--from", dest="start")
    rg.add_argument("--to", dest="end")
    rg.add_argument("--week", choices=["this", "last"])
    rg.add_argument("--save", action="store_true", help="scrive il report in reports/")

    fl = sub.add_parser("fill", help="grammi per chiudere i nutrienti che restano")
    fl.add_argument("--date")
    fl.add_argument("--foods", nargs="+", required=True)
    fl.add_argument("--nutrients", nargs="+", required=True,
                    choices=["kcal", "protein", "carbs", "fat"])

    f = sub.add_parser("food")
    fs = f.add_subparsers(dest="fcmd", required=True)
    fs.add_parser("list")
    s = fs.add_parser("search"); s.add_argument("query")
    s = fs.add_parser("show"); s.add_argument("id")
    s = fs.add_parser("add")
    s.add_argument("--id", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--state", required=True, choices=STATES)
    s.add_argument("--source", required=True)
    for n in CORE:
        s.add_argument(f"--{n}", type=float, required=True)
    s.add_argument("--fiber", type=float)
    s.add_argument("--sugar", type=float)
    s.add_argument("--sodium-mg", dest="sodium_mg", type=float)
    s.add_argument("--salt", type=float, help="sale g/100g dall'etichetta (convertito in sodio)")
    s.add_argument("--alias", action="append")
    s.add_argument("--note")
    s.add_argument("--force", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    profile = load_profile()
    try:
        if args.cmd == "now":
            now = dt.datetime.now(tz())
            m = suggest_meal(now.time())
            print(f"{now:%Y-%m-%d %H:%M} ({WEEKDAYS[now.weekday()]}) — pasto suggerito: "
                  f"{m or 'nessuno (chiedere)'}")
        elif args.cmd == "add":
            date = parse_date(args.date)
            if args.food:
                if args.grams is None:
                    raise TrackError("--grams è obbligatorio con --food.")
                add_food(date, args.meal, args.food, args.grams, args.note)
            else:
                add_recipe(date, args.meal, args.recipe, args.portions, args.note)
            print(render_day(date, profile, only_meal=args.meal.lower()))
        elif args.cmd == "remove":
            date = parse_date(args.date)
            e = remove_entry(date, args.meal, args.index)
            print(f"Rimosso: {e['name']} {e['grams']} g\n")
            print(render_day(date, profile))
        elif args.cmd == "show":
            print(render_day(parse_date(args.date), profile))
        elif args.cmd == "summary":
            date = parse_date(args.date)
            print(f"=== {date} ===\n" + table_vs_targets(total(day_entries(load_day(date))), profile))
        elif args.cmd == "range":
            if args.week:
                start, end = week_bounds(args.week)
            else:
                if not args.start:
                    raise TrackError("Serve --week oppure --from/--to.")
                start, end = parse_date(args.start), parse_date(args.end or args.start)
            text = render_range(range_stats(start, end), profile)
            print(text)
            if args.save:
                iso = start.isocalendar()
                name = (f"{iso.year}-W{iso.week:02d}.md" if args.week
                        else f"{start}_{end}.md")
                p = root() / "reports" / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text + "\n")
                print(f"\nSalvato in {p.relative_to(root())}")
        elif args.cmd == "fill":
            date = parse_date(args.date)
            foods = load_foods()
            tot = total(day_entries(load_day(date)))
            rem = remaining(tot, targets(profile))
            grams = solve_fill(foods, args.foods, args.nutrients, rem)
            entries = [make_entry(f, foods[f], g) for f, g in grams.items() if g > 0]
            print(f"Per chiudere {', '.join(LABELS[n] for n in args.nutrients)} del {date}:")
            for f, g in grams.items():
                print(f"  {foods[f]['name']} [{foods[f].get('state')}]: {g} g")
            print(f"  apporto: {fmt_values(total(entries), tracked_nutrients(profile))}")
            after = dict(total(day_entries(load_day(date)) + entries))
            print("\nGiornata dopo questo pasto:\n" + table_vs_targets(after, profile))
        elif args.cmd == "food":
            print(food_cmd(args, profile))
    except (TrackError, ValueError) as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
