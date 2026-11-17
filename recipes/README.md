# Ricette

Un file YAML per piatto ricorrente: `recipes/<id>.yaml`.

```yaml
name: Pasta al pomodoro
portions: 2            # le quantità sotto si riferiscono a 2 porzioni
ingredients:
  - {food_id: pasta_secca_crudo, grams: 160}
  - {food_id: passata_pomodoro, grams: 200}
  - {food_id: olio_evo, grams: 10}
```

Uso: `python3 scripts/track.py add --meal pranzo --recipe pasta_pomodoro --portions 1`

Gli ingredienti vengono scalati e registrati come voci singole (con `recipe: <id>`),
ognuna con il proprio snapshot. Tutti i `food_id` devono esistere nel catalogo.
