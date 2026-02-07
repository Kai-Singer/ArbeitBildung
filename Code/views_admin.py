from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse
from django.contrib import messages
from datetime import datetime, timedelta
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
import json
import os
from collections import Counter 
import pandas as pd
import matplotlib.pyplot as plt

DATA_DIR = '/var/www/django-project/arbeitbildung/data'
ADMIN_JSON = '/var/www/django-project/arbeitbildung/data/admin/admin.json'
DATA_SCHULEN = '/var/www/django-project/arbeitbildung/data/bildungseinrichtungen'
DATA_UNTERNEHMEN = '/var/www/django-project/arbeitbildung/data/unternehmen'

# Louis Raisch

##############################
######### Dashboard ##########
##############################

def admin_dashboard(request):
  
    username = request.session.get("admin_username", "Admin")
    
    unternehmen_count = 0
    try:
        for datei in os.listdir(DATA_UNTERNEHMEN):
            if datei.lower().endswith(".json") and datei.startswith("u"):
                unternehmen_count += 1
    except Exception:
        unternehmen_count = 0

    nutzer_statistik = berechne_nutzerstatistik()
    arbeitslosenquote = nutzer_statistik.get("arbeitslosenquote", 0)

    unread_count = 0
    try:
        with open(ADMIN_JSON, "r", encoding="utf-8") as f:
            adminDaten = json.load(f)
        unread_count = sum(1 for n in adminDaten.get("postfach", []) if n.get("status") is True)
    except Exception:
        unread_count = 0

    return render(request, "arbeitbildung/admin/dashboard.html", {
        "role": "admin",
        "active_page": "admin_dashboard",
        "username": username,

        #Template Werte
        "unternehmen_count": unternehmen_count,
        "arbeitslosenquote": arbeitslosenquote,
        "unread_count": unread_count,
    })

##############################
######### Statisiken #########
##############################

BUERGER_DIR = "/var/www/django-project/arbeitbildung/data/buerger"

def lade_alle_buerger():
    """Alle Bürgerdateien laden und JSON-Objekte zurückgeben."""
    buerger = []

    for file in os.listdir(BUERGER_DIR):
        if not file.endswith(".json"):
            continue

        pfad = os.path.join(BUERGER_DIR, file)

        try:
            with open(pfad, "r", encoding="utf-8") as f:
                buerger.append(json.load(f))
        except:
            print(f"[WARNUNG] Fehler beim Lesen von {file}")

    return buerger



def berechne_nutzerstatistik():
    #Berechnet die KPIs für die Bürger
    buerger_liste = lade_alle_buerger()

    total = len(buerger_liste)
    if total == 0:
        return {
            "total_citizens": 0,
            "arbeitslosenquote": 0,
            "bildungsdauer": 0,
            "avg_lebenslauf_entries": 0,
        }

    arbeitslos_count = 0
    bildungs_dauern = []
    lebenslauf_counts = []

    for b in buerger_liste:

        lebenslauf = b.get("lebenslauf", [])
        lebenslauf_counts.append(len(lebenslauf))

        for eintrag in lebenslauf:

            # Arbeitslosenquote
            if eintrag.get("art") == "arbeitslos":
                arbeitslos_count += 1

            # Bildungsdauer für Schule/Studium/Ausbildung
            if eintrag.get("art") in ["schueler", "ausbildung", "studium", "duales_studium"]:

                beginn = eintrag.get("beginn")
                ende = eintrag.get("ende")

                try:
                    d_start = datetime.strptime(beginn, "%Y-%m-%d")
                    d_ende = datetime.strptime(ende, "%Y-%m-%d") if ende else datetime.now()

                    diff = (d_ende - d_start).days / 365
                    bildungs_dauern.append(diff)

                except Exception as e:
                    print("[FEHLER] Bildungsdauer konnte nicht berechnet werden:", e)

    # KPIs berechnen
    arbeitslosenquote = round((arbeitslos_count / total) * 100, 1)      #arbeitslos durch Bürger in %, 1 Nachkommastelle runden
    bildungsdauer = round(sum(bildungs_dauern) / len(bildungs_dauern), 2) if bildungs_dauern else 0     #Bildungsdauer Jahre durch Bildungseinträge und auf 2 Nachkommastellen runden
    lebenslauf_eintraege = round(sum(lebenslauf_counts) / total, 2)     #Lebenslaufeinträge durch Anzahl Bürger, 2 Nachkommastellen

    return {
        "total_citizens": total,
        "arbeitslosenquote": arbeitslosenquote,
        "bildungsdauer": bildungsdauer,
        "lebenslauf_eintraege": lebenslauf_eintraege,
    }



def admin_statistiken(request):

    username = request.session.get("admin_username", "Admin")

    nutzer_statistik = berechne_nutzerstatistik()


    # ------------------------------------
    # Diagramm Statusverteilung der Bürger
    # ------------------------------------

    status_counter = Counter()  # Zählercontainer anlegen {status_counter["status"] = 0}

    for file in os.listdir(BUERGER_DIR):    #BUERGER_DIR s. oben
        if not file.endswith(".json"):
            continue

        with open(os.path.join(BUERGER_DIR, file), "r", encoding="utf-8") as f:
            b = json.load(f)

        lebenslauf = b.get("lebenslauf", [])
        #wenn Lebenslauf leer
        if not lebenslauf:
            status_counter["Unbekannt"] += 1
            continue

        # Aktuellen Eintrag suchen
        aktueller = None
        for eintrag in lebenslauf:
            if eintrag.get("ende") is False:
                aktueller = eintrag
                break

        # Fallback -> letzter Eintrag der Liste nehmen, nur wenn Code scheitert, falsche JSONS abfangen
        if not aktueller:
            aktueller = lebenslauf[-1]      #Index von hinten gezählt

        art = (aktueller.get("art") or "").lower()

        # richtigen Status finden
        if art == "schueler":
            status = "Schüler"
        elif art in ["studium", "duales_studium"]:
            status = "Studium"
        elif art == "ausbildung":
            status = "Ausbildung"
        elif art == "anstellung":
            status = "Arbeit"
        elif art == "arbeitslos":
            status = "Arbeitslos"
        elif art in ["rente", "rentner"]:
            status = "Rente"
        else:
            status = "Unbekannt"

        status_counter[status] += 1


    # Chart speichern
    if status_counter:
        labels = list(status_counter.keys())
        values = list(status_counter.values())

        pd.Series(values, index=labels).plot(
            kind="pie",     #Tortendiagramm
            autopct="%1.1f%%",      #Prozentwerte, eine nachkommastelle
            startangle=90   #startet senkrecht
        )
        plt.title("Statusverteilung der Bürger")
        plt.ylabel("")
        plt.tight_layout()
        plt.savefig("/var/www/django-project/arbeitbildung/static/imgs/statusverteilung_chart.png")     #wird hier gespeichert
        plt.close()


    # Sophie Schumann

    # Bildungseinrichtung Statistik
    schulen = []
    anzahl_schulen = 0
    plaetze_gesamt = 0
    plaetze_frei = 0
    auslastungen = []
    schularten = []

    for datei in os.listdir(DATA_SCHULEN):
        if datei.lower().endswith(".json") and datei.startswith("b"):
            pfad = os.path.join(DATA_SCHULEN, datei)
            with open(pfad, "r", encoding="utf-8") as f:
                schule = json.load(f)

            if not schule.get("aktiv", False):
                continue

            gesamt = int(schule.get("plaetze_gesamt", 0))
            frei = max(gesamt - len(schule.get("schueler", [])), 0)
            auslastung = int(((gesamt - frei) / gesamt) * 100) if gesamt > 0 else 0

            anzahl_schulen += 1
            plaetze_gesamt += gesamt
            plaetze_frei += frei
            auslastungen.append(auslastung)
            schularten.append(schule.get("schulart", "Unbekannt"))

            # Werte für Template
            schule["plaetze_frei"] = frei
            schule["auslastung"] = auslastung
            schulen.append(schule)

    auslastung_avg = round(sum(auslastungen) / len(auslastungen), 1) if auslastungen else 0
    schularten_verteilung = pd.Series(dict(Counter(schularten)))  # z.B. {'Gymnasium': 3, 'Grundschule': 5}

    # Diagramm erstellen 
    
    schularten_verteilung.plot(kind='bar')
    plt.title("Verteilung der Schularten")
    plt.xlabel("Schulart")
    plt.ylabel("Anzahl der Schulen")
    plt.tight_layout() #Passt die Abstände im Diagramm automatisch an

    # Pfad zum Static-Ordner speichert das Diagramm dort
    chart_path = os.path.join('/var/www/django-project/arbeitbildung/static/imgs/schularten_chart.png')
    plt.savefig(chart_path)
    plt.close()

    #----------------------------------------------------------------------------
    # Kennwortsuche Schulen
    #----------------------------------------------------------------------------
    filter_schulen_kennwort = ""
    filter_schulen_art = "all"

    if request.method == "POST":
        filter_schulen_kennwort = request.POST.get("filter_schulen_kennwort", "").strip()
        filter_schulen_art = request.POST.get("filter_schulen_art", "all").strip()

    gefilterte_schulen = []

    for schule in schulen:
        passt_name = True
        passt_schulart = True

        # Filter für Name
        if filter_schulen_kennwort:
            passt_name = filter_schulen_kennwort.lower() in schule.get("name", "").lower()

        # Filter für Schulart
        if filter_schulen_art != "all":
            passt_schulart = schule.get("schulart") == filter_schulen_art

        # Beide Bedingungen müssen stimmen
        if passt_name and passt_schulart:
            gefilterte_schulen.append(schule)

    schulen = gefilterte_schulen

    # Leonie Waimer

    ##############################
    # Arbeitsmarkt Statistik
    ##############################
    aktiveStellen = 0
    bewerbungenGesamt = 0
    stellen = []
    statusCounter = Counter()
    stellenBewerbungen = Counter()
    for datei in os.listdir(DATA_UNTERNEHMEN):
        if datei.lower().endswith(".json") and datei.startswith("u"):
            pfad = os.path.join(DATA_UNTERNEHMEN, datei)
            with open(pfad, "r", encoding="utf-8") as file:
                unternehmen = json.load(file)
            unternehmensName = unternehmen.get("name", "Unbekanntes Unternehmen")
            for bewerbung in unternehmen.get("bewerbungen", []):
                bewerbungenGesamt += 1
                statusCounter[bewerbung.get("status", "Unbekannt")] += 1
                stellenBewerbungen[bewerbung.get("stelle")] += 1
            for stelle in unternehmen.get("stellen", []):
                if stelle.get("aktiv") and not stelle.get("besetzt"):
                    aktiveStellen += 1
                    stellen.append({
                        "unternehmen": unternehmensName,
                        "bezeichnung": stelle.get("bezeichnung"),
                        "bewerbungen": stellenBewerbungen.get(stelle.get("id"), 0),
                    })
    avgBewerbungen = round(bewerbungenGesamt / aktiveStellen, 2) if aktiveStellen > 0 else 0
    if statusCounter:
        pd.Series(statusCounter).plot(kind='pie', autopct='%1.1f%%', startangle=90)
        plt.title("Bewerbungsstatus Verteilung")
        plt.ylabel("")  
        plt.tight_layout()
        plt.savefig('/var/www/django-project/arbeitbildung/static/imgs/bewerbungsstatus_chart.png')
        plt.close()
    #----------------------------------------------------------------------------
    # Kennwortsuche Stellenübersicht (aktive Stellen)
    #----------------------------------------------------------------------------
    filter_stellen_kennwortsuche = ""
    if request.method == "POST":
        filter_stellen_kennwortsuche = request.POST.get("filter_stellen_kennwortsuche", "").strip()
    gefilterteStellen = []
    if filter_stellen_kennwortsuche != "":
        suchbegriff = filter_stellen_kennwortsuche.lower()
        for stellenEintrag in stellen:
            name = stellenEintrag.get("unternehmen").lower()
            bezeichnung = stellenEintrag.get("bezeichnung").lower()
            if suchbegriff in name or suchbegriff in bezeichnung:
                gefilterteStellen.append(stellenEintrag)
    else:
        gefilterteStellen = stellen
    
    # Louis Raisch
    return render(request, 'arbeitbildung/admin/statistiken.html', {
        'role': 'admin',
        'active_page': 'admin_statistiken',
        'username': username,

        # Sophie Schumann
         # KPIs Schulen
        'schulen': schulen,
        'anzahl_schulen': anzahl_schulen,
        'plaetze_gesamt': plaetze_gesamt,
        'plaetze_frei': plaetze_frei,
        'auslastung_avg': auslastung_avg,
        'schularten_verteilung': schularten_verteilung,

        # Leonie Waimer
        # KPIs Arbeitsmarkt
        'aktive_stellen': aktiveStellen,
        'bewerbungen_gesamt': bewerbungenGesamt,
        'avg_bewerbungen': avgBewerbungen,
        'stellen': gefilterteStellen,
        'filter_stellen_kennwortsuche': filter_stellen_kennwortsuche,
    })

# Louis Raisch

##############################
########## Postfach ##########
##############################

def get_target_file(ziel_id):
    """
    Ziel-Empfänger bestimmen:
    buerger0001 → /data/buerger/buerger0001.json
    u0001       → /data/unternehmen/u0001.json
    b0001       → /data/bildungseinrichtungen/b0001.json
    """
    if ziel_id.startswith("buerger"):
        return f"{DATA_DIR}/buerger/{ziel_id}.json"     #Fallback für richtige Bürger IDs

    if ziel_id.startswith("u"):
        return f"{DATA_DIR}/unternehmen/{ziel_id}.json"

    if ziel_id.startswith("b"):
        return f"{DATA_DIR}/bildungseinrichtungen/{ziel_id}.json"
    
    return f"{DATA_DIR}/buerger/{ziel_id}.json"   #Für richtige Bürger IDs von Meldewesen API


def write_response_to_target(ziel_id, text):
    
    target_path = get_target_file(ziel_id)
    if target_path is None:
        return False, "Ungültige Ziel-ID."

    if not os.path.exists(target_path):
        return False, f"Die Datei für '{ziel_id}' existiert nicht."

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Falls kein Postfach existiert:
        if "postfach" not in data:
            data["postfach"] = []

        data["postfach"].insert(0, {    #Nachricht ganz oben anreihen
            "sender": "Admin",
            "beschreibung": text,
            "status": True   # neue Nachricht = ungelesen
        })

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return True, f"Antwort erfolgreich an {ziel_id} gesendet."

    except Exception as e:
        return False, f"Fehler beim Speichern: {str(e)}"


def admin_postfach(request):

    username = request.session.get("admin_username", "Admin")

    # Admin JSON einlesen
    with open(ADMIN_JSON, "r", encoding="utf-8") as f:
        adminDaten = json.load(f)

    # POST-Aktion (gelesen / alle gelesen / antworten)
    if request.method == "POST":

        # Einzelne Nachricht als gelesen markieren
        if "index" in request.POST:
            index = int(request.POST.get("index"))
            adminDaten["postfach"][index]["status"] = False
            messages.success(request, "Nachricht als gelesen markiert.")

        # Alle als gelesen markieren
        elif "alle_gelesen" in request.POST:
            for eintrag in adminDaten["postfach"]:
                eintrag["status"] = False
            messages.success(request, "Alle Nachrichten wurden gelesen.")

        # Eine Antwort wurde versendet
        elif "antwort_index" in request.POST:
            ziel_id = request.POST.get("ziel")
            text = request.POST.get("antwort_text")

            success, msg = write_response_to_target(ziel_id, text)
            if success:
                messages.success(request, msg)
            else:
                messages.error(request, msg)

        # Admin-Postfach speichern (nur Statusänderungen)
        with open(ADMIN_JSON, "w", encoding="utf-8") as f:
            json.dump(adminDaten, f, indent=2, ensure_ascii=False)

        return redirect("admin/postfach")

    # GET Request → Seite rendern
    return render(request, "arbeitbildung/admin/postfach.html", {
        "role": "admin",
        "active_page": "admin_postfach",
        "username": username,
        "postfach": adminDaten["postfach"],
    })

# Sophie Schumann

##############################
########## Anmeldung #########
##############################

ADMIN_USERNAME = "Armin"
ADMIN_PASSWORT = "123"


def admin_anmeldung(request):

    if request.method == "POST":
        benutzername = request.POST.get("benutzername")
        passwort = request.POST.get("passwort")

        if benutzername == ADMIN_USERNAME and passwort == ADMIN_PASSWORT:

            # Admin-Session setzen
            request.session["ist_admin"] = True
            request.session["admin_username"] = benutzername

            messages.success(request, f"Willkommen zurück, {benutzername}.")
            return redirect("admin/dashboard")

        messages.error(request, "Benutzername oder Passwort ist falsch.")

    return render(request, "arbeitbildung/admin/anmeldung.html")
