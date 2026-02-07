from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse
from django.contrib import messages
from datetime import datetime, timedelta
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
from django.contrib.sessions.models import Session
import json
import os
import requests
import datetime
DATA_DIR = '/var/www/django-project/arbeitbildung/data/bildungseinrichtungen'
adminData = '/var/www/django-project/arbeitbildung/data/admin/admin.json'
SCHUELER_DIR = '/var/www/django-project/arbeitbildung/data/buerger'

##############################
######### Dashboard ##########
##############################

def bildungseinrichtungen_dashboard(request):

   # Bildungseinrichtungs-ID aus Session holen 
    bildungseinrichtung_id = request.session.get("einrichtung_id")
    json_pfad = os.path.join(DATA_DIR, f"{bildungseinrichtung_id}.json")

    with open(json_pfad, "r", encoding="utf-8") as file:
        bildungseinrichtungsregister = json.load(file)

    # Schulart
    schulart = bildungseinrichtungsregister.get("schulart", "-")

    # Schüler zählen
    schueler_liste = []
    for schueler in bildungseinrichtungsregister.get("schueler", []):
        schueler_liste.append(schueler)
    anzahl_schueler = len(schueler_liste)

    # ungelesene Nachrichten zählen
    ungelesene_nachrichten = []
    for nachricht in bildungseinrichtungsregister.get("postfach", []):
        if nachricht.get("status", False):
            ungelesene_nachrichten.append(nachricht)
    anzahl_ungelesene_nachrichten = len(ungelesene_nachrichten)

    if request.method == 'POST':
        nachricht = request.POST.get('nachricht', '').strip()
        if nachricht:
            with open(adminData, "r", encoding="utf-8") as file:
                adminDaten = json.load(file)
                adminDaten["postfach"].insert(0,{
                "sender": bildungseinrichtung_id,
                "beschreibung": nachricht,
                "status": True
                })
            with open(adminData, "w", encoding="utf-8") as file:
                json.dump(adminDaten, file, indent=2, ensure_ascii=False)
            messages.success(request, "Deine Nachricht wurde erfolgreich gesendet!")
            return redirect('bildungseinrichtungen/dashboard')


    return render(request, 'arbeitbildung/bildungseinrichtungen/dashboard.html', {
    	'role': 'bildungseinrichtungen',
    	'active_page': 'bildungseinrichtungen_dashboard',
    	'username': bildungseinrichtungsregister.get("name", "Bildungseinrichtung"),
    	'schulart': schulart,
    	'anzahl_schueler': anzahl_schueler,
    	'anzahl_ungelesene_nachrichten': anzahl_ungelesene_nachrichten,
        'bildungseinrichtung_id': bildungseinrichtung_id
  	})


##############################
########## Schüler ###########
##############################

API_Meldewesen_URL = "http://[2001:7c0:2320:2:f816:3eff:fef8:f5b9]:8000/einwohnermeldeamt/api/person"

def hole_buergername(buerger_id):
    try:
        api_response = requests.get(f"{API_Meldewesen_URL}/{buerger_id}", timeout=3)
        api_response.raise_for_status()
        data = api_response.json()

        vorname = data.get("vorname", "").strip()
        nachname = (
            data.get("nachname_neu")
            or data.get("nachname_geburt")
            or ""
        ).strip()

        name = f"{vorname} {nachname}".strip()
        return name if name else f"ID {buerger_id}"

    except Exception:
        return f"ID {buerger_id}"


def bildungseinrichtungen_schueler(request):

  # Bildungseinrichtungs-ID
    bildungseinrichtung_id = request.session.get("einrichtung_id")
    bildung_json_pfad = os.path.join(DATA_DIR, f"{bildungseinrichtung_id}.json")

    # JSON der Bildungseinrichtung laden
    with open(bildung_json_pfad, "r", encoding="utf-8") as file:
        daten = json.load(file)

        # POST Zeugnis speichern
    if request.method == "POST":
        action = request.POST.get("action")

        if action != "schueler_kuendigen":
            schueler_id = request.POST.get("schueler_id")
            neue_beschreibung = request.POST.get("beschreibung", "")
            neue_note = request.POST.get("note", "")

            schueler_json_pfad = os.path.join(SCHUELER_DIR, f"{schueler_id}.json")
            if os.path.exists(schueler_json_pfad):
                with open(schueler_json_pfad, "r", encoding="utf-8") as f:
                    schueler_daten = json.load(f)
                        
                 # Den aktuellsten Lebenslauf-Eintrag für diese Schule finden
                letzter_eintrag = None
                for eintrag in reversed(schueler_daten.get("lebenslauf", [])):
                    if eintrag.get("art") == "schueler" and eintrag.get("bildungseinrichtung") == bildungseinrichtung_id:
                        letzter_eintrag = eintrag
                        break

                if letzter_eintrag:
                    letzter_eintrag["zeugnis"] = {
                        "beschreibung": neue_beschreibung,
                        "abschlussnote": neue_note
                    }
                      
                # Datei speichern
                with open(schueler_json_pfad, "w", encoding="utf-8") as f:
                    json.dump(schueler_daten, f, indent=2, ensure_ascii=False)

                #  Nachricht anzeigen
                messages.success(request, f"Zeugnis von Schüler {schueler_id} gespeichert.")
            

        #Schüler kündigen
        elif request.POST.get("action") == "schueler_kuendigen":
            schueler_id = request.POST.get("schueler_id")
            schueler_name = hole_buergername(schueler_id)
            verbleibende_schueler = []

            heute = datetime.date.today().strftime("%Y-%m-%d")

            # Jeden Schüler prüfen, ob er nicht der zu kündigende ist
            for schueler in daten.get("schueler", []):
                if str(schueler.get("id")) != str(schueler_id):
                    verbleibende_schueler.append(schueler)

            # Die neue Schülerliste zurücksetzen
            daten["schueler"] = verbleibende_schueler

            # JSON der Bildungseinrichtung speichern
            with open(bildung_json_pfad, "w", encoding="utf-8") as f:
                json.dump(daten, f, indent=2, ensure_ascii=False)

            #Lebenslauf des Schülers aktualisieren
            schueler_json_pfad = os.path.join(SCHUELER_DIR, f"{schueler_id}.json")
            if os.path.exists(schueler_json_pfad):
                with open(schueler_json_pfad, "r", encoding="utf-8") as f:
                    schueler_daten = json.load(f)

                # Passenden Eintrag für diese Bildungseinrichtung finden
                lebenslauf = schueler_daten.get("lebenslauf", [])
                if len(lebenslauf) > 0:
                    if lebenslauf[-1].get("art") == "schueler" and lebenslauf[-1].get("bildungseinrichtung") == bildungseinrichtung_id:
                        lebenslauf[-1]["ende"] = heute  # Ende auf heute setzen

                # Datei zurückschreiben
                with open(schueler_json_pfad, "w", encoding="utf-8") as f:
                    json.dump(schueler_daten, f, indent=2, ensure_ascii=False)

                # Postfach kündigung      
                # Postfach der Bildungseinrichtung 
                postfach = daten.get("postfach")
                if postfach is None:
                    postfach = []
                    daten["postfach"] = postfach
                # Nachricht ganz oben einfügen
                postfach.insert(0, {
                    "sender": "Ich",
                    "beschreibung": f"Schüler: {schueler_name} erfolgreich rausgeschmissen",
                    "verlinkung": "/bildungseinrichtungen/schueler",
                    "status": True
                })

                # Bildungseinrichtung speichern 
                with open(bildung_json_pfad, "w", encoding="utf-8") as f:
                    json.dump(daten, f, indent=2, ensure_ascii=False)

            messages.success(request, f"Schüler {schueler_id} wurde gekündigt (Ende: {heute}).")
                
        # Seite neu laden, um Änderungen zu sehen
        return redirect("bildungseinrichtungen/schueler")  


    schueler_liste = []
    for schueler in daten.get("schueler", []):
        schueler_id = schueler.get("id")
        # Funktion aufrufen für Name aus API 
        schueler_name = hole_buergername(schueler_id)
        schueler_json_pfad = os.path.join(SCHUELER_DIR, f"{schueler_id}.json")

        einschulung = "Unbekannt"
        voraussichtlicher_abschluss = "Unbekannt"
        aktuelle_note = "Unbekannt"
        aktuelle_beschreibung = ""

        # JSON des Schülers laden, wenn er existiert
        if os.path.exists(schueler_json_pfad):
            with open(schueler_json_pfad, "r", encoding="utf-8") as file:
                schueler_daten = json.load(file)

            # Lebenslauf-Eintrag für diese Bildungseinrichtung finden
            # Lebenslauf-Eintrag für diese Bildungseinrichtung finden (nur aktueller Eintrag)
            lebenslauf = schueler_daten.get("lebenslauf", [])
            letzter_schul_eintrag = None

            for eintrag in reversed(lebenslauf):  # von hinten nach vorne
                if eintrag.get("art") == "schueler" and eintrag.get("bildungseinrichtung") == bildungseinrichtung_id:
                    letzter_schul_eintrag = eintrag
                    break  # ersten (letzten chronologisch) Treffer nehmen

            if letzter_schul_eintrag:
                einschulung = letzter_schul_eintrag.get("beginn", "Unbekannt")
                voraussichtlicher_abschluss = letzter_schul_eintrag.get("ende", "Unbekannt")
                aktuelle_note = letzter_schul_eintrag.get("zeugnis", {}).get("abschlussnote", "Unbekannt")
                aktuelle_beschreibung = letzter_schul_eintrag.get("zeugnis", {}).get("beschreibung", "Unbekannt")


        schueler_liste.append({
            'id': schueler_id,
            'name': schueler_name,
            'einschulung': einschulung,
            'voraussichtlicher_abschluss': voraussichtlicher_abschluss,
            'aktuelle_note': aktuelle_note,
            'aktuelle_beschreibung': aktuelle_beschreibung
        })

    # Suchbegriff aus GET-Parameter holen und in Kleinbuchstaben umwandeln
    eingetragener_name = request.GET.get("search", "").strip().lower()

    # Wenn ein Suchbegriff eingegeben wurde, Schüler filtern
    if eingetragener_name:
        gefundene_schueler = []
        for schueler in schueler_liste:
            schueler_name = schueler.get('name', '').lower()
            if eingetragener_name in schueler_name:
                gefundene_schueler.append(schueler)
        schueler_liste = gefundene_schueler


    return render(request, 'arbeitbildung/bildungseinrichtungen/schueler.html', {
    	'role': 'bildungseinrichtungen',
    	'active_page': 'bildungseinrichtungen_schueler',
    	'username': daten.get('name', 'Bildungseinrichtung'),
        'schueler': schueler_liste,
        'bildungseinrichtung_id': bildungseinrichtung_id,
        'suchbegriff': eingetragener_name
  	})

##############################
########## Postfach ##########
##############################

def bildungseinrichtungen_postfach(request):
   
   # Bildungseinrichtungs-ID aus Session 
    bildungseinrichtung_id = request.session.get("einrichtung_id")
    json_pfad = os.path.join(DATA_DIR, f"{bildungseinrichtung_id}.json")

    # JSON der Bildungseinrichtung laden
    with open(json_pfad, "r", encoding="utf-8") as file:
        daten = json.load(file)

    # POST-Handling: Nachrichten als gelesen markieren
    if request.method == 'POST':
        if "index" in request.POST:
            index = int(request.POST.get('index'))
            daten['postfach'][index]['status'] = False
            messages.success(request, "Die Nachricht wurde als gelesen markiert.")
        elif "alle_gelesen" in request.POST:
            for eintrag in daten['postfach']:
                eintrag['status'] = False
            messages.success(request, "Alle Nachrichten wurden als gelesen markiert.")

        # JSON wieder speichern
        with open(json_pfad, "w", encoding="utf-8") as file:
            json.dump(daten, file, indent=2, ensure_ascii=False)

    return render(request, 'arbeitbildung/bildungseinrichtungen/postfach.html', {
        'role': 'bildungseinrichtungen',
        'active_page': 'bildungseinrichtungen_postfach',
        'username': daten.get('name', 'Bildungseinrichtung'),
        'postfach': daten.get('postfach', []),
        'bildungseinrichtung_id': bildungseinrichtung_id
    })
  
##############################
########## Anmeldung #########
##############################

def bildungseinrichtungen_anmeldung(request):

    # JSON mit Login-Daten 
    benutzerdatei = os.path.join(DATA_DIR, "nutzer.json")

    with open(benutzerdatei, "r", encoding="utf-8") as file:
        benutzerliste = json.load(file)

    if request.method == "POST":
        einrichtung_id = request.POST.get("einrichtung_id")
        passwort = request.POST.get("passwort")

        for eintrag in benutzerliste:
            if str(eintrag["id"]) == str(einrichtung_id) and eintrag["passwort"] == passwort:
                # Session setzen mit ID der Bildungseinrichtung
                request.session["einrichtung_id"] = eintrag["id"]
                request.session["einrichtung_name"] = eintrag["name"]

                messages.success(request, f"Erfolgreich angemeldet als {eintrag['name']}.")
                return redirect("bildungseinrichtungen/dashboard")

        messages.error(request, "ID oder Passwort falsch.")

    return render(request, "arbeitbildung/bildungseinrichtungen/anmeldung.html")

##############################
##### Registreierung #########
##############################

def bildungseinrichtungen_registrierung(request):

    if request.method == 'POST':

        name = request.POST.get('benutzername')
        schulart = request.POST.get('schulart')
        adresse = request.POST.get('adresse')
        plaetze_gesamt = request.POST.get('plaetze_gesamt')
        dauer = request.POST.get('dauer')
        passwort = request.POST.get('passwort')
        

        # ----- ID bestimmen anhand von vorhandenen Dateien -----
        all_ids = []
        for f in os.listdir(DATA_DIR):
            if f.startswith("b") and f.endswith(".json"):
                with open(os.path.join(DATA_DIR, f), encoding="utf-8") as file:
                    data = json.load(file)
                    all_ids.append(int(data["id"][1:]))

        next_id = f"b{max(all_ids, default=0) + 1:04d}"

        # Neues JSON für die Bildungseinrichtung
        neue_daten = {
            "id": next_id,
            "aktiv": True,
            "name": name,
            "schulart": schulart,
            "adresse": adresse,
            "plaetze_gesamt": plaetze_gesamt,
            "dauer": dauer,
            "schueler": [],
            "postfach": []
        }

        # JSON-Datei speichern
        with open(os.path.join(DATA_DIR, f"{next_id}.json"), "w", encoding="utf-8") as file:
            json.dump(neue_daten, file, indent=4, ensure_ascii=False)

        # Passwortdatei öffnen / erstellen
        passwort_datei = os.path.join(DATA_DIR, "nutzer.json")

        try:
            with open(passwort_datei, "r", encoding="utf-8") as file:
                nutzerliste = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            nutzerliste = []

        # Passwort-Daten anhängen
        nutzerliste.append({
            "id": next_id,
            "name": name,
            "passwort": passwort
            })
      
        # Passwortliste speichern
        with open(passwort_datei, "w", encoding="utf-8") as file:
            json.dump(nutzerliste, file, indent=4, ensure_ascii=False)

        infoText = f"Neue Registrierung:\n\nBildungseinrichtungs-ID: {next_id}\nBitte merken Sie sich diese ID für die Anmeldung."

        return render(request, 'arbeitbildung/bildungseinrichtungen/registrierung.html', {
          "infoText": infoText,
          "neueID": next_id
        })


    return render(request, 'arbeitbildung/bildungseinrichtungen/registrierung.html', {
          "infoText": None
        })


