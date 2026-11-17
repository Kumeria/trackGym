# trackGym — regole per Claude

Questo repo è il diario alimentare dell'utente. L'utente scrive in italiano, in
linguaggio naturale, cosa ha mangiato (o manda una foto di un'etichetta / un barcode).
Il tuo compito: registrare, calcolare con lo script, mostrare i totali rispetto ai target,
committare e pushare. Rispondi sempre in italiano.

## Struttura

- `profile.yaml` — target giornalieri, nutrienti extra da tracciare, peso e obiettivo, fuso orario.
- `foods/foods.json` — catalogo, valori **per 100 g**, con `state` (crudo | cotto | n/a) e
  `source` (label | off:<barcode> | manual).
- `log/AAAA/MM/AAAA-MM-GG.yaml` — un file per giorno, pasti colazione/pranzo/cena/snack.
  Ogni voce ha `food_id`, `grams` e lo snapshot `values`: modificare il catalogo NON cambia i giorni passati.
- `recipes/<id>.yaml` — piatti ricorrenti (vedi `recipes/README.md`).
- `reports/` — riepiloghi settimanali generati.
- `scripts/track.py`, `scripts/off.py`, `scripts/tests/`.

## Regole fondamentali

1. **Niente aritmetica a mente.** Ogni kcal, macro, totale, media o residuo viene da
   `scripts/track.py`. Riporta i numeri che lo script stampa, non ricalcolarli né arrotondarli diversamente.
2. **Mai inventare valori nutrizionali.** Non usare valori "tipici" dalla memoria.
   Se un alimento non è nel catalogo: chiedi etichetta (foto o valori per 100 g) o barcode,
   oppure di' esplicitamente che non hai il dato. Non registrare nulla finché il dato non c'è.
   `source: manual` solo per valori che l'utente ti detta esplicitamente (indicando da dove vengono).
3. **Crudo vs cotto, sempre.** Ogni alimento del catalogo ha uno stato. Se l'utente non dice
   se il peso è a crudo o a cotto per un alimento in cui conta (pasta, riso, cereali, legumi,
   carne, pesce, patate…), chiediglielo. Non convertire mai crudo↔cotto con fattori di resa
   inventati: se il catalogo ha solo la versione crudo e l'utente ha pesato cotto, chiedi.
   Usa id distinti (es. `riso_basmati_crudo`, `riso_basmati_cotto`).
4. **Pasto.** Se l'utente non lo indica, esegui `python3 scripts/track.py now`: se suggerisce
   un pasto usalo (e dillo nella risposta), se dice "chiedere" chiedi all'utente.
   Se l'utente parla al passato ("ieri a cena") usa `--date` appropriato.
5. **Dopo ogni inserimento** mostra: voci aggiunte, totale del pasto, tabella della giornata
   con quanto resta rispetto ai target (è esattamente ciò che stampa `add`).
6. **Dopo ogni modifica ai dati** (log, catalogo, profilo, ricette, report): commit e push SUBITO.
   Il container è effimero: senza push i dati sono persi.
   ```bash
   git add -A && git commit -m "<messaggio>" && git push origin HEAD:main
   ```
   Messaggi: `log: 2026-11-17 pranzo +pasta 100g, +pollo 200g`, `foods: +yogurt_greco (label)`,
   `profile: target aggiornati`, `report: 2026-W46`. Se il push fallisce, riprova e avvisa l'utente.
   I dati vivono su `main`: l'utente ha autorizzato il push diretto su `main` per ogni
   modifica ai dati, anche se la sessione lavora su un branch `claude/...`.
7. **Inizio sessione:** `git fetch origin main && git merge --ff-only origin/main` prima di toccare i dati.

## Comandi

```bash
python3 scripts/track.py now                                   # ora locale + pasto suggerito
python3 scripts/track.py food search pollo                     # cerca nel catalogo
python3 scripts/track.py food show pasta_secca_crudo
python3 scripts/track.py add --meal pranzo --food pasta_secca_crudo --grams 100
python3 scripts/track.py add --meal cena --recipe pasta_pomodoro --portions 1
python3 scripts/track.py add --date ieri --meal snack --food mela --grams 150 --note "fuori casa"
python3 scripts/track.py show [--date 2026-11-17]              # dettaglio giorno con indici
python3 scripts/track.py remove --meal pranzo --index 2 [--date ...]
python3 scripts/track.py summary [--date ...]
python3 scripts/track.py range --week last [--save]            # settimana scorsa (lun–dom)
python3 scripts/track.py range --from 2026-11-01 --to 2026-11-15
python3 -m unittest discover -s scripts/tests                  # test
```

`--date` accetta `AAAA-MM-GG`, `oggi`, `ieri`.

### Aggiungere un alimento al catalogo

- **Da etichetta** (foto): leggi i valori per 100 g dalla tabella nutrizionale. Se l'etichetta
  riporta solo valori per porzione, chiedi i valori per 100 g o la dimensione della porzione
  — non fare la proporzione a mente. Il sale in etichetta va passato con `--salt` (lo script
  lo converte in sodio). Prima di salvare, ripeti all'utente i valori letti per conferma.
  ```bash
  python3 scripts/track.py food add --id yogurt_greco_0 --name "Yogurt greco 0% (Marca)" \
    --state n/a --source label --kcal 57 --protein 10 --carbs 3.5 --fat 0 \
    --fiber 0 --sugar 3.5 --salt 0.1 --alias "greco"
  ```
- **Da barcode**: prima anteprima, poi salva indicando lo stato.
  ```bash
  python3 scripts/off.py 8001234567890                 # anteprima (cache se già presente)
  python3 scripts/off.py 8001234567890 --state crudo --id pasta_marca_crudo --save
  ```
  Se OFF non ha i dati completi, lo script non salva: chiedi l'etichetta.
  Mostra all'utente nome e valori trovati: i dati OFF sono crowdsourced, conferma che corrispondano al prodotto.
  Se `world.openfoodfacts.org` non è raggiungibile, procedi solo con etichette/inserimenti manuali.
- **Senza etichetta né barcode** (l'utente non ce l'ha): non usare valori a memoria. Cerca su
  OFF un prodotto reale, diffuso in Italia, dello stesso tipo e salvalo con
  `off.py <barcode> --save --note "rappresentativo: ..."`. Dillo all'utente indicando marca e
  valori, e proponigli di sostituirlo con l'etichetta vera quando ce l'ha.
- **Correzioni** al catalogo: `food add ... --force`. I giorni già registrati non cambiano;
  se l'utente vuole correggere un giorno passato, `remove` + `add` su quella data.

## Immagini

L'utente può mandare foto. Come trattarle:

- **Etichetta nutrizionale** → leggi i valori per 100 g, ripetili all'utente per conferma,
  poi `food add --source label`. Solo valori per porzione → chiedi quelli per 100 g
  (o il peso della porzione), non fare proporzioni a mente. Parti illeggibili → chiedi, non indovinare.
- **Codice a barre** → leggi le cifre sotto le barre e usa `off.py`. Se non sono leggibili
  con certezza, chiedi all'utente di scriverle.
- **Fronte confezione** → identifica prodotto, marca e stato (crudo/cotto); se non è già
  nel catalogo servono anche tabella nutrizionale o barcode.
- **Display della bilancia** → leggi i grammi; se l'unità o la tara non sono chiare, chiedi.
- **Foto del piatto** → identifica gli alimenti, ma **non stimare mai i grammi a occhio**:
  chiedi i pesi, o se corrisponde a una porzione/ricetta già registrata. Per condimenti
  invisibili (olio, burro, sughi) chiedi esplicitamente se ci sono e quanti grammi.

Flusso consigliato: la prima volta etichetta o barcode → catalogo; poi basta il peso.

## Consultare il passato

- "Com'è andata la settimana scorsa?" → `range --week last`, poi commenta i numeri stampati
  (media vs target, giorni registrati, giorni in target). Se l'utente lo vuole conservare, `--save` e commit.
- "Cosa ho mangiato martedì?" → `show --date <data>` (calcola la data dal calendario con `now`
  come riferimento, se serve usa `date` della shell).

## Profilo

Target, peso e obiettivo stanno in `profile.yaml`; si modificano solo su indicazione dell'utente.
`targets.kcal: auto` = kcal calcolate dallo script come proteine×4 + carboidrati×4 + grassi×9.
Le kcal dei singoli alimenti restano quelle dell'etichetta / OFF.
Nuova pesata: aggiungi `{date: AAAA-MM-GG, kg: ...}` in `weight_log` e aggiorna `body.weight_kg`.
Se i target sono `null`, la tabella mostra `n/d` nella colonna target: ricordalo all'utente.

## Stile risposta

Breve. Dopo un inserimento: incolla l'output dello script in un blocco di codice e aggiungi
al massimo una riga di commento (es. "ti restano ~X g di proteine per cena" usando il numero stampato).
