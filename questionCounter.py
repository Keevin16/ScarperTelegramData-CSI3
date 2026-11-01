#!/usr/bin/env python3
"""
questionCounter_v2 - conta le domande per giorno nei gruppi Telegram
(export JSON di Telegram Desktop) e misura quanto e' affidabile il conteggio.

Cosa fa:
  1. Riconosce una domanda con regole migliori del solo "?":
       - contiene un "?" (link esclusi), oppure
       - inizia con una formula interrogativa tipica ("come si...", "dove posso...",
         "qualcuno sa...", "c'e'...", "posso...", "si puo'...")
       - ignora messaggi troppo corti (default < 3 parole), solo emoji,
         messaggi inoltrati e messaggi inviati tramite bot
  2. Produce, per ogni file: CSV giornaliero + 2 grafici PNG, piu' un riepilogo.
  3. Crea un campione da etichettare a mano (--campione) e calcola
     precisione / recall / accuratezza stimate (--valuta).

Autori e ID non vengono mai letti ne' salvati. Il file del campione contiene
pero' il TESTO dei messaggi: tienilo solo in locale e cancellalo dopo la
valutazione.

Requisiti:  pip install matplotlib

Esempi (da /Volumes/Dracarys-T7/telegramData):
    python3 questionCounter_v2.py data/*.json -o risultati_v2
    python3 questionCounter_v2.py data/DSU.json -o risultati_v2 --campione 200
    python3 questionCounter_v2.py --valuta risultati_v2/DSU_campione.csv
    python3 questionCounter_v2.py data/DSU.json --regola punto    # vecchio metodo, per confronto
"""
import argparse
import csv
import json
import math
import os
import random
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

# ---------------------------------------------------------------- regole

URL_RE = re.compile(r"(?:https?://|www\.|t\.me/)\S+", re.I)
PAROLA_RE = re.compile(r"[^\W\d_]+", re.U)  # solo parole fatte di lettere (emoji escluse)

SALUTI = r"(?:(?:ciao|salve|buongiorno|buonasera|buonpomeriggio|ehi|hey|raga|ragazzi|ragazze|" \
         r"scusate|scusa|scusi|ok|allora|senti|sentite)\W+)*"

INIZI_DOMANDA = [
    r"qualcuno\b",
    r"(?:c'è|ci\s+sono|esiste|esistono)\b",
    r"(?:come|dove|quando|perch[eé]|chi|cosa|quale|quali|quanto|quanta|quanti|quante)\s+"
    r"(?:si|mi|ci|posso|possiamo|può|puo|devo|dovrei|faccio|facciamo|fare|funziona|funzionano|"
    r"è|e|sono|ha|hanno|fa|vanno|va|trovo|trovare|iscrivo|iscriversi|ottengo|ottenere|"
    r"richiedo|prenoto|prendo|conviene|serve|servono|bisogna|devono)\b",
    r"(?:posso|possiamo|potrei|potremmo|potete|puoi|sapete|sapreste|conoscete|avete)\b",
    r"(?:è\s+possibile|si\s+può|si\s+puo)\b",
]
INIZIO_RE = re.compile(r"^\s*" + SALUTI + r"(?:" + "|".join(INIZI_DOMANDA) + r")", re.I)


def pulisci(testo):
    return URL_RE.sub(" ", testo.replace("’", "'")).strip()


def e_domanda(testo, regola="estesa", min_parole=3):
    t = pulisci(testo)
    if len(PAROLA_RE.findall(t)) < min_parole:
        return False
    if "?" in t:
        return True
    if regola == "estesa" and INIZIO_RE.match(t):
        return True
    return False


# ---------------------------------------------------------------- lettura

def testo_messaggio(msg):
    """Il campo 'text' puo' essere una stringa o una lista di pezzi/entita'."""
    t = msg.get("text", "")
    if isinstance(t, str):
        return t
    parti = []
    for p in t:
        if isinstance(p, str):
            parti.append(p)
        elif isinstance(p, dict):
            if p.get("type") in ("link", "text_link"):
                continue
            parti.append(p.get("text", ""))
    return "".join(parti)


def raccogli_messaggi(dati):
    """Supporta sia l'export di una singola chat sia quello completo."""
    if "messages" in dati:
        yield from dati["messages"]
    elif "chats" in dati:
        for chat in dati["chats"]["list"]:
            yield from chat.get("messages", [])


def analizza(dati, regola, min_parole, raccogli_testi=False):
    """Ritorna (tot, domande, stats, testi). 'testi' e' riempito solo se serve il campione."""
    tot = defaultdict(int)
    domande = defaultdict(int)
    stats = {"servizio": 0, "inoltrati_bot": 0, "validi": 0}
    testi = []
    for msg in raccogli_messaggi(dati):
        if msg.get("type") != "message":
            stats["servizio"] += 1
            continue
        if "forwarded_from" in msg or "via_bot" in msg:
            stats["inoltrati_bot"] += 1
            continue
        stats["validi"] += 1
        giorno = date.fromisoformat(msg["date"][:10])
        tot[giorno] += 1
        testo = testo_messaggio(msg)
        pred = e_domanda(testo, regola, min_parole)
        if pred:
            domande[giorno] += 1
        if raccogli_testi and testo.strip():
            testi.append((testo, pred))
    return tot, domande, stats, testi


# ---------------------------------------------------------------- output

def serie_continua(tot, domande):
    inizio, fine = min(tot), max(tot)
    giorni, n_msg, n_dom = [], [], []
    g = inizio
    while g <= fine:
        giorni.append(g)
        n_msg.append(tot.get(g, 0))
        n_dom.append(domande.get(g, 0))
        g += timedelta(days=1)
    return giorni, n_msg, n_dom


def salva_csv(path, giorni, n_msg, n_dom):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["data", "messaggi", "domande"])
        for g, m, d in zip(giorni, n_msg, n_dom):
            w.writerow([g.isoformat(), m, d])


def media_mobile(valori, finestra=7):
    out = []
    for i in range(len(valori)):
        blocco = valori[max(0, i - finestra + 1): i + 1]
        out.append(sum(blocco) / len(blocco))
    return out


def grafici(prefisso, giorni, n_dom, titolo):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator

    colore, colore_linea = "#2F6FED", "#F2994A"

    def stile(ax):
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)

    # --- domande al giorno
    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=150)
    ax.bar(giorni, n_dom, color=colore, alpha=0.35, width=0.9, label="Domande al giorno")
    ax.plot(giorni, media_mobile(n_dom), color=colore_linea, linewidth=2.8,
            label="Media mobile 7 giorni")
    ax.set_title(f"{titolo}\nDomande al giorno", fontsize=16, fontweight="bold", loc="left")
    ax.set_ylabel("Numero di domande", fontsize=12)
    loc = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    ax.set_ylim(0, max(max(n_dom), 1) * 1.25)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.legend(frameon=False, fontsize=11, loc="upper right", ncol=2)
    stile(ax)
    fig.tight_layout()
    fig.savefig(f"{prefisso}_grafico_giornaliero.png")
    plt.close(fig)

    # --- media per giorno della settimana
    nomi = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
    somma, cont = [0] * 7, [0] * 7
    for g, d in zip(giorni, n_dom):
        somma[g.weekday()] += d
        cont[g.weekday()] += 1
    medie = [s / c if c else 0 for s, c in zip(somma, cont)]
    fig, ax = plt.subplots(figsize=(8, 5.5), dpi=150)
    barre = ax.bar(nomi, medie, color=colore)
    for b, v in zip(barre, medie):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}", ha="center", va="bottom", fontsize=11)
    ax.set_title(f"{titolo}\nDomande medie per giorno della settimana",
                 fontsize=16, fontweight="bold", loc="left")
    ax.set_ylabel("Domande (media)", fontsize=12)
    ax.set_ylim(0, max(max(medie), 1) * 1.15)
    stile(ax)
    fig.tight_layout()
    fig.savefig(f"{prefisso}_grafico_settimana.png")
    plt.close(fig)


# ---------------------------------------------------------------- campione + valutazione

def crea_campione(path, testi, n, seed):
    """Campione stratificato: meta' dai messaggi previsti 'domanda', meta' dagli altri.
    Serve per stimare sia la precisione (quante previste sono vere)
    sia la recall (quante vere domande ci sfuggono)."""
    rng = random.Random(seed)
    si = [t for t, p in testi if p]
    no = [t for t, p in testi if not p]
    n_si = min(n // 2, len(si))
    n_no = min(n - n_si, len(no))
    scelti = [(t, "si") for t in rng.sample(si, n_si)] + [(t, "no") for t in rng.sample(no, n_no)]
    rng.shuffle(scelti)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "previsione", "testo", "etichetta"])
        for i, (t, p) in enumerate(scelti, 1):
            w.writerow([i, p, t.replace("\n", " ")[:400], ""])
    with open(path + ".meta.json", "w", encoding="utf-8") as f:
        json.dump({"tot_si": len(si), "tot_no": len(no), "n_si": n_si, "n_no": n_no}, f)
    return n_si, n_no


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def valuta(path):
    with open(path + ".meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    vero = {"si": True, "s": True, "1": True, "y": True, "yes": True,
            "no": False, "n": False, "0": False}
    # strati: per ogni previsione, (etichette vere, etichette totali)
    k = {"si": 0, "no": 0}
    n = {"si": 0, "no": 0}
    non_etich = 0
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            e = (r["etichetta"] or "").strip().lower()
            if e not in vero:
                non_etich += 1
                continue
            n[r["previsione"]] += 1
            k[r["previsione"]] += 1 if vero[e] else 0
    if non_etich:
        print(f"Attenzione: {non_etich} righe senza etichetta valida (si/no), ignorate.")
    if n["si"] == 0 or n["no"] == 0:
        raise SystemExit("Servono etichette in entrambi i gruppi (previsione si e no).")

    prec = k["si"] / n["si"]                       # tra le previste domande, quante lo sono davvero
    fnr = k["no"] / n["no"]                        # tra le NON previste, quante erano domande
    tp = meta["tot_si"] * prec
    fn = meta["tot_no"] * fnr
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * recall / (prec + recall) if prec + recall else 0.0
    tot = meta["tot_si"] + meta["tot_no"]
    acc = (tp + meta["tot_no"] * (1 - fnr)) / tot
    p_lo, p_hi = wilson(k["si"], n["si"])

    print(f"Etichettati: {n['si']} previsti 'domanda' + {n['no']} previsti 'non domanda'")
    print(f"Precisione  : {prec:5.1%}  (IC 95%: {p_lo:.0%}-{p_hi:.0%})  "
          f"-> di 100 messaggi contati come domande, ~{prec*100:.0f} lo sono davvero")
    print(f"Recall      : {recall:5.1%}  -> ~{recall*100:.0f} domande vere su 100 vengono trovate")
    print(f"F1          : {f1:5.1%}")
    print(f"Accuratezza : {acc:5.1%}  (su tutti i messaggi)")
    print(f"Domande contate dallo script : {meta['tot_si']}")
    print(f"Domande reali stimate        : {tp + fn:.0f}   (corretto per falsi positivi e negativi)")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export_json", nargs="*", help="uno o piu' file JSON di Telegram Desktop")
    ap.add_argument("-o", "--output", default="risultati_v2", help="cartella di output")
    ap.add_argument("--regola", choices=["estesa", "punto"], default="estesa",
                    help="'estesa' (default) = '?' + formule interrogative; 'punto' = solo '?'")
    ap.add_argument("--min-parole", type=int, default=3,
                    help="messaggi con meno parole non contano (default 3)")
    ap.add_argument("--campione", type=int, default=0, metavar="N",
                    help="crea un campione di N messaggi da etichettare a mano")
    ap.add_argument("--seed", type=int, default=42, help="seme del campionamento (riproducibile)")
    ap.add_argument("--valuta", metavar="CSV", help="calcola precisione/recall da un campione etichettato")
    args = ap.parse_args()

    if args.valuta:
        valuta(args.valuta)
        return
    if not args.export_json:
        ap.error("indica almeno un file JSON (oppure --valuta)")

    os.makedirs(args.output, exist_ok=True)
    riepilogo = []

    for percorso in args.export_json:
        nome = os.path.splitext(os.path.basename(percorso))[0]
        with open(percorso, encoding="utf-8") as f:
            dati = json.load(f)
        tot, domande, stats, testi = analizza(dati, args.regola, args.min_parole,
                                              raccogli_testi=args.campione > 0)
        if not tot:
            print(f"[{nome}] nessun messaggio trovato, salto.", file=sys.stderr)
            continue

        giorni, n_msg, n_dom = serie_continua(tot, domande)
        prefisso = os.path.join(args.output, nome)
        salva_csv(f"{prefisso}_per_giorno.csv", giorni, n_msg, n_dom)
        grafici(prefisso, giorni, n_dom, nome.replace("_", " "))

        riepilogo.append([nome, giorni[0].isoformat(), giorni[-1].isoformat(),
                          sum(n_msg), sum(n_dom), f"{sum(n_dom) / max(sum(n_msg), 1):.1%}"])
        print(f"[{nome}] {len(giorni)} giorni, {sum(n_msg)} messaggi, {sum(n_dom)} domande "
              f"(esclusi {stats['inoltrati_bot']} inoltrati/bot, {stats['servizio']} di servizio)")

        if args.campione > 0:
            p = f"{prefisso}_campione.csv"
            a, b = crea_campione(p, testi, args.campione, args.seed)
            print(f"[{nome}] campione: {p}  ({a} previsti 'domanda' + {b} previsti 'non domanda')")
            print("          -> compila la colonna 'etichetta' con si/no, poi:")
            print(f"             python3 {os.path.basename(sys.argv[0])} --valuta {p}")

    with open(os.path.join(args.output, "riepilogo.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["gruppo", "dal", "al", "messaggi", "domande", "quota_domande"])
        w.writerows(riepilogo)
    print(f"Fatto. Risultati in: {args.output}/")


if __name__ == "__main__":
    main()
