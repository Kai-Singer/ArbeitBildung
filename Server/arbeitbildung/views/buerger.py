from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse, HttpResponse
from django.contrib import messages
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse
import json
import os
import requests

from geopy.geocoders import Nominatim

DATA_DIR = '/var/www/django-project/arbeitbildung/data'
API_Meldewesen_URL = "http://[2001:7c0:2320:2:f816:3eff:fef8:f5b9]:8000/einwohnermeldeamt/api/person"

#################################################
######### Update des Bürgers - Crontab ##########
#################################################

def cron_run_age_update():
    buerger_dir = os.path.join(DATA_DIR, "buerger")
    rentner_heute = 0

    for file in os.listdir(buerger_dir):
        if not file.endswith(".json"):
            continue

        uid = file.replace(".json", "")
        wurde_rentner = update_buerger_status(uid)

        if wurde_rentner:
            rentner_heute += 1

    print(f"[CRON] {rentner_heute} Bürger wurden heute in den Ruhestand versetzt.")
    return rentner_heute



def erhalte_alter_buerger(buerger_id):
    try:
        r = requests.get(f"{API_Meldewesen_URL}/{buerger_id}", timeout=5)
        r.raise_for_status()
        data = r.json()

        geburtsdatum_str = data.get("geburtsdatum")
        if not geburtsdatum_str:
            print(f"[ALTER] {buerger_id}: kein geburtsdatum in API")
            return None

        try:
            geburtsdatum = datetime.strptime(geburtsdatum_str, "%Y-%m-%d")
        except ValueError:
            try:
                geburtsdatum = datetime.strptime(geburtsdatum_str, "%d.%m.%Y")
            except Exception as e:
                print(f"[ALTER] {buerger_id}: geburtsdatum-Format unerwartet ({geburtsdatum_str}): {e}")
                return None

        heute = datetime.now()
        alter = heute.year - geburtsdatum.year - ((heute.month, heute.day) < (geburtsdatum.month, geburtsdatum.day))

        print(f"[ALTER] {buerger_id}: erfolgreich abgerufen → {alter} Jahre")
        return alter

    except Exception as e:
        print(f"[ALTER] API-Fehler bei {buerger_id}: {e}")

    print(f"[ALTER] Kein Alter für {buerger_id} gefunden → Fallback None")
    return None




def update_buerger_status(uid):
    pfad = os.path.join(DATA_DIR, "buerger", f"{uid}.json")

    try:
        r = requests.get(f"{API_Meldewesen_URL}/{uid}", timeout=5)
        person = r.json()
        if person.get("sterbedatum") is not None or person.get("lebensstatus") == "tot":
            print(f"[STATUS] {uid}: Person ist tot → kein Renten-Update")
            return False
    except Exception as e:
        print(f"[STATUS] {uid}: Personendaten konnten nicht geprüft werden (weiter mit Alter): {e}")


    if not os.path.exists(pfad):
        print(f"[STATUS] Datei fehlt für {uid}")
        return False
    
    with open(pfad, "r", encoding="utf-8") as f:
        buerger = json.load(f)

    alter = erhalte_alter_buerger(uid)

    if alter is None:
        print(f"[STATUS] {uid}: Alter unbekannt → kein Update")
        return False

    if alter < 18:
        neuer_status = "schueler"
    elif alter >= 67:
        neuer_status = "rentner"
    else:
        neuer_status = "erwachsen"


    if neuer_status == "rentner":
        lebenslauf = buerger.get("lebenslauf", [])

        bereits_rentner = any(
            eintrag.get("art") == "rente"
            for eintrag in lebenslauf
        )

        if not bereits_rentner:
            heute = datetime.now().strftime("%Y-%m-%d")

            #Offene Jobs beenden
            for eintrag in lebenslauf:
                if eintrag.get("art") == "anstellung" and eintrag.get("ende") in (None, False):
                    eintrag["ende"] = heute

            bewerbungen = buerger.get("bewerbungen", [])
            betroffen = []

            # Bürgerseite offen/angebot -> zurückgezogen + rückmeldedatum
            for b in bewerbungen:
                if b.get("status") in ("offen", "angebot"):
                    b["status"] = "zurückgezogen"
                    b["rückmeldedatum"] = heute

                    unternehmen_id = b.get("arbeitgeber")
                    stelle_id = b.get("stelle")
                    if unternehmen_id and stelle_id:
                        betroffen.append((unternehmen_id, stelle_id))

            buerger["bewerbungen"] = bewerbungen

            # deduplizieren (damit wir nicht mehrfach in dasselbe uXXXX gehen)
            betroffen = list(dict.fromkeys(betroffen))

            # Unternehmensseite pro betroffenem Unternehmen die Bewerbung zurückziehen
            for unternehmen_id, stelle_id in betroffen:
                unternehmen_pfad = os.path.join(DATA_DIR, "unternehmen", f"{unternehmen_id}.json")

                if not os.path.isfile(unternehmen_pfad):
                    print(f"[RENTE] Unternehmen-Datei fehlt: {unternehmen_pfad}")
                    continue

                try:
                    with open(unternehmen_pfad, "r", encoding="utf-8") as f:
                        u = json.load(f)

                    # Stellenname für Postfachtext
                    stelle_name = next(
                        (s.get("bezeichnung") for s in u.get("stellen", []) if str(s.get("id")) == str(stelle_id)),
                        str(stelle_id)
                    )

                    # Bewerbungen in Unternehmens.json auf zurückgezogen setzen
                    for ub in u.get("bewerbungen", []):
                        ub_bewerber = ub.get("bewerber", ub.get("buerger"))

                        if (
                            str(ub_bewerber) == str(uid)
                            and str(ub.get("stelle")) == str(stelle_id)
                            and ub.get("status") in ("offen", "angebot")
                        ):
                            ub["status"] = "zurückgezogen"
                            ub["rückmeldedatum"] = heute

                    # Postfach im Unternehmen
                    u.setdefault("postfach", [])
                    u["postfach"].insert(0, {
                        "sender": ermittle_buerger_stammdaten(uid).get("name", "Unbekannt"),
                        "beschreibung": f"Der Bürger wurde in den Ruhestand versetzt. Bewerbung für '{stelle_name}' ({stelle_id}) wurde zurückgezogen.",
                        "verlinkung": "/unternehmen/bewerber",
                        "status": True
                    })

                    with open(unternehmen_pfad, "w", encoding="utf-8") as f:
                        json.dump(u, f, indent=2, ensure_ascii=False)

                    print(f"[RENTE] Bewerbung gespiegelt: {uid} -> {unternehmen_id}/{stelle_id}")

                except Exception as e:
                    print(f"[RENTE] Fehler beim Spiegeln in Unternehmen {unternehmen_id}: {e}")


            renteneintrag = {
                "beginn": heute,
                "ende": False,
                "art": "rente",
                "arbeitgeber": False,
                "stelle": False,
                "bildungseinrichtung": False,
                "zeugnis": {}
            }

            lebenslauf.append(renteneintrag)

            buerger.setdefault("postfach", [])
            buerger["postfach"].insert(0, {
                "sender": "System",
                "beschreibung": "Sie wurden automatisch in den Ruhestand versetzt.",
                "status": True
            })

            with open(pfad, "w", encoding="utf-8") as f:
                json.dump(buerger, f, indent=2, ensure_ascii=False)

            print(f"[STATUS] {uid}: automatisch in Rente versetzt.")
            return True

    print(f"[STATUS] {uid}: keine Änderung ({neuer_status}).")
    return False



#################################################
############# Abfrage Tod - Crontab #############
#################################################

def cron_run_person_tod():
    for file in os.listdir(os.path.join(DATA_DIR, "buerger")):
        if not file.endswith(".json"):
            continue
        buerger_id = file.replace(".json", "")

        try:
            # Todesstatus abfragen API Meldewesen
            r = requests.get(f"{API_Meldewesen_URL}/{buerger_id}", timeout = 5)
            data = r.json()

            if data.get("sterbedatum", None) is not None:
                datum = datetime.now().strftime("%Y-%m-%d")
                buerger_pfad = os.path.join(DATA_DIR, "buerger", f"{buerger_id}.json")
                unternehmen_id = None
                stelle_id = None
                bewerbungen_loeschen = []

                if os.path.isfile(buerger_pfad):
                    with open(buerger_pfad, "r", encoding="utf-8") as f:
                        buerger_daten = json.loads(f.read())
                    lebenslauf = buerger_daten.get("lebenslauf", [])

                    # Überspringen, wenn bereits tot
                    if len(lebenslauf) > 0 and lebenslauf[-1].get("art") == "tot":
                        continue

                    # Letzte Beschäftigung beenden
                    if len(lebenslauf) > 0:
                        lebenslauf[-1]["ende"] = datum
                        unternehmen_id = lebenslauf[-1].get("arbeitgeber", None)
                        stelle_id = lebenslauf[-1].get("stelle", None)

                    # Todeseintrag hinzufügen
                    lebenslauf.append({
                        "beginn": datum,
                        "ende": False,
                        "art": "tot",
                        "bildungseinrichtung": False,
                        "arbeitgeber": False,
                        "stelle": False,
                        "zeugnis": {}
                    })

                    # Aktuelle Bewerbungen beenden
                    bewerbungen = buerger_daten.get("bewerbungen", [])
                    for bewerbung in bewerbungen:
                        if bewerbung.get("status") in ("offen", "angebot"):
                            bewerbung["status"] = "zurückgezogen"
                            bewerbung["rückmeldedatum"] = datum
                            bewerbungen_loeschen.append({
                                "unternehmen_id": bewerbung.get("arbeitgeber"),
                                "stelle_id": bewerbung.get("stelle")
                            })
                    buerger_daten["bewerbungen"] = bewerbungen

                    # Nachricht ins Postfach schicken
                    buerger_daten.setdefault("postfach", [])
                    buerger_daten["postfach"].insert(0, {
                        "sender": "System",
                        "beschreibung": 'Deine letzte Beschäftigung und alle aktuellen Bewerbungen wurden aufgrund deines Todes beendet.',
                        "verlinkung": reverse('buerger/lebenslauf'), # Erstellt die entsprechende URL des Servers
                        "status": True
                    })

                    # abspeichern
                    buerger_daten["lebenslauf"] = lebenslauf
                    with open(buerger_pfad, "w", encoding="utf-8") as f:
                        f.write(json.dumps(buerger_daten, indent=2, ensure_ascii=False))
                    print(f"[CRON] Bürger wurde erfolgreich auf tot gestellt ({buerger_id})")

                # Aktuelle Anstellung beenden
                if unternehmen_id and stelle_id:
                    unternehmen_pfad = os.path.join(DATA_DIR, "unternehmen", f"{unternehmen_id}.json")
                    if os.path.isfile(unternehmen_pfad):
                        with open(unternehmen_pfad, "r", encoding="utf-8") as f:
                            unternehmen_daten = json.loads(f.read())

                        # Stelle freigeben
                        stelle_name = None
                        stellen = unternehmen_daten.get("stellen", [])
                        for stelle in stellen:
                            if stelle.get("id", None) == stelle_id:
                                stelle["buerger"] = ""
                                stelle["besetzt"] = False
                                stelle_name = stelle.get("bezeichnung", None)
                                break
                        unternehmen_daten["stellen"] = stellen

                        if stelle_name is None:
                            print(f"[CRON] Stelle des verstorbenen Bürgers konnte nicht gefunden werden ({buerger_id})")
                            continue

                        # Nachricht ins Postfach schicken
                        unternehmen_daten.setdefault("postfach", [])
                        unternehmen_daten["postfach"].insert(0, {
                            "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                            "beschreibung": f'Der Bürger ist verstorben. Die Stelle "{stelle_name}" wurde wieder freigegeben.',
                            "verlinkung": reverse('unternehmen/bewerber'), # Erstellt die entsprechende URL des Servers
                            "status": True
                        })

                        # abspeichern
                        with open(unternehmen_pfad, "w", encoding="utf-8") as f:
                            f.write(json.dumps(unternehmen_daten, indent=2, ensure_ascii=False))
                        print(f"[CRON] Stelle des verstorbenen Bürgers wurde freigegeben ({buerger_id})")

                # Bewerbungen bei Unternehmen löschen
                for bewerbung in bewerbungen_loeschen:
                    unternehmen_id = bewerbung.get("unternehmen_id")
                    stelle_id = bewerbung.get("stelle_id")

                    unternehmen_pfad = os.path.join(DATA_DIR, "unternehmen", f"{unternehmen_id}.json")
                    if os.path.isfile(unternehmen_pfad):
                        with open(unternehmen_pfad, "r", encoding="utf-8") as f:
                            unternehmen_daten = json.loads(f.read())

                        # Bewerbung entfernen
                        bewerbungen = unternehmen_daten.get("bewerbungen", [])
                        for bewerbung in bewerbungen:
                            if (bewerbung.get("buerger") == buerger_id and bewerbung.get("stelle") == stelle_id and bewerbung.get("status") in ("offen", "angebot")):
                                bewerbung["status"] = "zurückgezogen"
                                bewerbung["rückmeldedatum"] = datum
                        unternehmen_daten["bewerbungen"] = bewerbungen

                        # Nachricht ins Postfach schicken
                        unternehmen_daten.setdefault("postfach", [])
                        unternehmen_daten["postfach"].insert(0, {
                            "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                            "beschreibung": f'Der Bürger ist verstorben. Alle aktuellen Bewerbungen wurden zurückgezogen.',
                            "verlinkung": reverse('unternehmen/bewerber'), # Erstellt die entsprechende URL des Servers
                            "status": True
                        })

                        #abspeichern
                        with open(unternehmen_pfad, "w", encoding="utf-8") as f:
                            f.write(json.dumps(unternehmen_daten, indent=2, ensure_ascii=False))
                        print(f"[CRON] Bewerbung des verstorbenen Bürgers wurde zurückgezogen ({buerger_id})")

        except Exception as e:
            print(f"[CRON] Bürger konnte nicht auf tot gestellt werden ({buerger_id}): {e}")



#################################################
############ Abfrage Haft - Crontab #############
#################################################

def cron_run_person_haft():
    for file in os.listdir(os.path.join(DATA_DIR, "buerger")):
        if not file.endswith(".json"):
            continue
        buerger_id = file.replace(".json", "")

        datum = datetime.now().strftime("%Y-%m-%d")
        buerger_pfad = os.path.join(DATA_DIR, "buerger", f"{buerger_id}.json")
        if not os.path.isfile(buerger_pfad):
            continue

        with open(buerger_pfad, "r", encoding="utf-8") as f:
            buerger_daten = json.loads(f.read())
        lebenslauf = buerger_daten.get("lebenslauf", [])

        # Prüfen, ob bereits in Haft
        ist_in_haft = False
        if len(lebenslauf) > 0 and lebenslauf[-1].get("art") == "haft":
            ist_in_haft = True

        try:
            r = requests.get(f"{API_Meldewesen_URL}/{buerger_id}", timeout = 5)
            data = r.json()
            api_ist_in_haft = data.get("haft_status", False)

            # API-Abfrage -> In Haft
            if api_ist_in_haft is True:
                if ist_in_haft:
                    continue
                
                # Letzte Beschäftigung beenden
                unternehmen_id = None
                stelle_id = None
                if len(lebenslauf) > 0:
                    lebenslauf[-1]["ende"] = datum
                    unternehmen_id = lebenslauf[-1].get("arbeitgeber", None)
                    stelle_id = lebenslauf[-1].get("stelle", None)

                # Haft-Eintrag hinzufügen
                lebenslauf.append({
                    "beginn": datum,
                    "ende": False,
                    "art": "haft",
                    "bildungseinrichtung": False,
                    "arbeitgeber": False,
                    "stelle": False,
                    "zeugnis": {}
                })

                # Aktuelle Bewerbungen beenden
                bewerbungen_loeschen = []
                bewerbungen = buerger_daten.get("bewerbungen", [])
                for bewerbung in bewerbungen:
                    if bewerbung.get("status") in ("offen", "angebot"):
                        bewerbung["status"] = "zurückgezogen"
                        bewerbung["rückmeldedatum"] = datum
                        bewerbungen_loeschen.append({
                            "unternehmen_id": bewerbung.get("arbeitgeber"),
                            "stelle_id": bewerbung.get("stelle")
                        })
                buerger_daten["bewerbungen"] = bewerbungen

                # Nachricht ins Postfach schicken
                buerger_daten.setdefault("postfach", [])
                buerger_daten["postfach"].insert(0, {
                    "sender": "System",
                    "beschreibung": f'Deine letzte Beschäftigung und alle aktuellen Bewerbungen wurden aufgrund deiner Inhaftierung beendet.',
                    "verlinkung": reverse('buerger/lebenslauf'), # Erstellt die entsprechende URL des Servers
                    "status": True
                })

                # abspeichern
                buerger_daten["lebenslauf"] = lebenslauf
                with open(buerger_pfad, "w", encoding="utf-8") as f:
                    f.write(json.dumps(buerger_daten, indent=2, ensure_ascii=False))
                print(f"[CRON] Bürger wurde erfolgreich auf in Haft gestellt ({buerger_id})")

                # Aktuelle Anstellung beenden
                if unternehmen_id and stelle_id:
                    unternehmen_pfad = os.path.join(DATA_DIR, "unternehmen", f"{unternehmen_id}.json")
                    if os.path.isfile(unternehmen_pfad):
                        with open(unternehmen_pfad, "r", encoding="utf-8") as f:
                            unternehmen_daten = json.loads(f.read())

                        # Stelle freigeben
                        stelle_name = None
                        stellen = unternehmen_daten.get("stellen", [])
                        for stelle in stellen:
                            if stelle.get("id", None) == stelle_id:
                                stelle["buerger"] = ""
                                stelle["besetzt"] = False
                                stelle_name = stelle.get("bezeichnung", None)
                                break
                        unternehmen_daten["stellen"] = stellen

                        if stelle_name is None:
                            print(f"[CRON] Stelle des inhaftierten Bürgers konnte nicht gefunden werden ({buerger_id})")
                            continue

                        # Nachricht ins Postfach schicken
                        unternehmen_daten.setdefault("postfach", [])
                        unternehmen_daten["postfach"].insert(0, {
                            "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                            "beschreibung": f'Der Bürger ist inhaftiert. Die Stelle "{stelle_name}" wurde wieder freigegeben.',
                            "verlinkung": reverse('unternehmen/bewerber'), # Erstellt die entsprechende URL des Servers
                            "status": True
                        })

                        # abspeichern
                        with open(unternehmen_pfad, "w", encoding="utf-8") as f:
                            f.write(json.dumps(unternehmen_daten, indent=2, ensure_ascii=False))
                        print(f"[CRON] Stelle des inhaftierten Bürgers wurde freigegeben ({buerger_id})")

                # Bewerbungen bei Unternehmen löschen
                for bewerbung in bewerbungen_loeschen:
                    unternehmen_id = bewerbung.get("unternehmen_id")
                    stelle_id = bewerbung.get("stelle_id")

                    unternehmen_pfad = os.path.join(DATA_DIR, "unternehmen", f"{unternehmen_id}.json")
                    if os.path.isfile(unternehmen_pfad):
                        with open(unternehmen_pfad, "r", encoding="utf-8") as f:
                            unternehmen_daten = json.loads(f.read())

                        # Bewerbung entfernen
                        bewerbungen = unternehmen_daten.get("bewerbungen", [])
                        for bewerbung in bewerbungen:
                            if (bewerbung.get("buerger") == buerger_id and bewerbung.get("stelle") == stelle_id and bewerbung.get("status") in ("offen", "angebot")):
                                bewerbung["status"] = "zurückgezogen"
                                bewerbung["rückmeldedatum"] = datum
                        unternehmen_daten["bewerbungen"] = bewerbungen

                        # Nachricht ins Postfach schicken
                        unternehmen_daten.setdefault("postfach", [])
                        unternehmen_daten["postfach"].insert(0, {
                            "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                            "beschreibung": f'Der Bürger ist inhaftiert. Alle aktuellen Bewerbungen wurden zurückgezogen.',
                            "verlinkung": reverse('unternehmen/bewerber'), # Erstellt die entsprechende URL des Servers
                            "status": True
                        })

                        #abspeichern
                        with open(unternehmen_pfad, "w", encoding="utf-8") as f:
                            f.write(json.dumps(unternehmen_daten, indent=2, ensure_ascii=False))
                        print(f"[CRON] Bewerbung des inhaftierten Bürgers wurde zurückgezogen ({buerger_id})")

            # API-Abfrage -> Nicht in Haft
            else:
                if not ist_in_haft:
                    continue

                # Haft-Eintrag beenden
                lebenslauf[-1]["ende"] = datum
                buerger_daten["lebenslauf"] = lebenslauf

                # Nachricht ins Postfach schicken
                buerger_daten.setdefault("postfach", [])
                buerger_daten["postfach"].insert(0, {
                    "sender": "System",
                    "beschreibung": f'Dein Haftstatus wurde aufgehoben. Jobangebote können wieder angenommen werden.',
                    "verlinkung": reverse('buerger/lebenslauf'), # Erstellt die entsprechende URL des Servers
                    "status": True
                })

                # abspeichern
                with open(buerger_pfad, "w", encoding="utf-8") as f:
                    f.write(json.dumps(buerger_daten, indent=2, ensure_ascii=False))
                print(f"[CRON] Haftstatus des Bürgers wurde erfolgreich aufgehoben ({buerger_id})")

        except Exception as e:
            print(f"[CRON] Haftstatus des Bürgers konnte nicht aktualisiert werden ({buerger_id}): {e}")

def get_kind_alter():
    url = "http://[2001:7c0:2320:2:f816:3eff:fe79:999d]/ro/gesetz_api/17"

    try:
        r = requests.get(url, timeout = 5)
        data = r.json()
        kind_alter = data.get("api_relevant", [15])
        kind_alter = int(kind_alter[0])
        return kind_alter
    
    except Exception as e:
        print(f"API-Fehler beim Abrufen des rechtlichen Alters für Kinder: {e}")
        return 15

#################################################
######### Abfrage Berufsverbot - Crontab ########
#################################################

def get_berufsverbote():
    url = "http://[2001:7c0:2320:2:f816:3eff:fe79:999d]/ro/gesetz_api/10"

    try:
        # Gibt Berufe zurück, für die ein Berufsverbot nach § 10 besteht
        r = requests.get(url, timeout = 5)
        data = r.json()
        berufe = data.get("api_relevant", [])
        return berufe
    
    except Exception as e:
        print(f"API-Fehler beim Abrufen der Berufsverbote: {e}")
        return []
    
def check_berufsverbot(buerger_id):
    url = "http://[2001:7c0:2320:2:f816:3eff:fe79:999d]/ro/vorstrafen_api/"

    try:
        r = requests.get(f"{url}/{buerger_id}", timeout = 5)
        data = r.json()

        # gibt zurück, ob der Bürger eine Vorstrafe hat
        if len(data.get("vorstrafen", [])) > 0:
            return True
        else:
            return False

    except Exception as e:
        print(f"API-Fehler beim Überprüfen des Berufsverbots für {buerger_id}: {e}")
        return False

def cron_run_person_berufsverbot():
    berufsverbote = get_berufsverbote()
    datum = datetime.now().strftime("%Y-%m-%d")

    for file in os.listdir(os.path.join(DATA_DIR, "buerger")):
        if not file.endswith(".json"):
            continue
        buerger_id = file.replace(".json", "")

        try:
            berufsverbot = check_berufsverbot(buerger_id)

            # Überspringen, wenn kein Berufsverbot besteht
            if not berufsverbot:
                continue
        
            buerger_pfad = os.path.join(DATA_DIR, "buerger", f"{buerger_id}.json")
            if not os.path.isfile(buerger_pfad):
                print(f"[CRON] Bürgerdatei nicht gefunden für Berufsverbot ({buerger_id})")
                continue

            with open(buerger_pfad, "r", encoding="utf-8") as f:
                buerger_daten = json.loads(f.read())
            lebenslauf = buerger_daten.get("lebenslauf", [])

            # Aktuelle Bewerbungen überprüfen
            bewerbungen = buerger_daten.get("bewerbungen", [])
            for bewerbung in bewerbungen:
                unternehmen_id = bewerbung.get("arbeitgeber", None)
                stelle_id = bewerbung.get("stelle", None)

                unternehmen_pfad = os.path.join(DATA_DIR, "unternehmen", f"{unternehmen_id}.json")
                if not os.path.isfile(unternehmen_pfad):
                    continue

                with open(unternehmen_pfad, "r", encoding="utf-8") as f:
                    unternehmen_daten = json.loads(f.read())

                # Bezeichnung der Stelle ermitteln
                stelle_name = None
                stellen = unternehmen_daten.get("stellen", [])
                for stelle in stellen:
                    if stelle.get("id", None) == stelle_id:
                        stelle_name = stelle.get("bezeichnung", None)
                        break
                
                if stelle_name is None:
                    continue

                # Überspringen, wenn die Stelle nicht unters Berufsverbot fällt
                if stelle_name not in berufsverbote:
                    continue

                # Bewerbung zurückziehen
                bewerbung["status"] = "zurückgezogen"
                bewerbung["rückmeldedatum"] = datum

                # Bewerbung auf Unternehmensseite entfernen
                bewerbungen = unternehmen_daten.get("bewerbungen", [])
                for bewerbung in bewerbungen:
                    if (bewerbung.get("buerger") == buerger_id and bewerbung.get("stelle") == stelle_id and bewerbung.get("status") in ("offen", "angebot")):
                        bewerbung["status"] = "zurückgezogen"
                        bewerbung["rückmeldedatum"] = datum
                unternehmen_daten["bewerbungen"] = bewerbungen

                # Nachricht ins Postfach schicken
                unternehmen_daten.setdefault("postfach", [])
                unternehmen_daten["postfach"].insert(0, {
                    "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                    "beschreibung": f'Der Bürger hat ein Berufsverbot für den Beruf, für den er sich beworben hat. Die Bewerbung für die Stelle "{stelle_name}" wurde zurückgezogen.',
                    "verlinkung": reverse('unternehmen/bewerber'), # Erstellt die entsprechende URL des Servers
                    "status": True
                })

                #abspeichern
                with open(unternehmen_pfad, "w", encoding="utf-8") as f:
                    f.write(json.dumps(unternehmen_daten, indent=2, ensure_ascii=False))
                print(f"[CRON] Bewerbung des Bürgers mit Berufsverbot wurde zurückgezogen ({buerger_id})")

            buerger_daten["bewerbungen"] = bewerbungen

            # Nachricht ins Postfach schicken
            buerger_daten.setdefault("postfach", [])
            buerger_daten["postfach"].insert(0, {
                "sender": "System",
                "beschreibung": 'Aufgrund deines Berufsverbots wurden alle deine aktuellen Bewerbungen, die davon betroffen sind, zurückgezogen.',
                "verlinkung": reverse('buerger/bewerbungen'), # Erstellt die entsprechende URL des Servers
                "status": True
            })

            # Überspringen, wenn keine Einträge im Lebenslauf
            if len(lebenslauf) <= 0:
                continue

            # Letzte Beschäftigung prüfen
            unternehmen_id = buerger_daten["lebenslauf"][-1].get("arbeitgeber", False)
            stelle_id = buerger_daten["lebenslauf"][-1].get("stelle", False)

            if not (unternehmen_id and stelle_id):
                continue

            unternehmen_pfad = os.path.join(DATA_DIR, "unternehmen", f"{unternehmen_id}.json")
            if not os.path.isfile(unternehmen_pfad):
                print(f"[CRON] Unternehmensdatei nicht gefunden für Berufsverbot ({buerger_id})")
                continue

            with open(unternehmen_pfad, "r", encoding="utf-8") as f:
                unternehmen_daten = json.loads(f.read())

            # Bezeichnung der Stelle ermitteln
            stelle_name = None
            stellen = unternehmen_daten.get("stellen", [])
            for stelle in stellen:
                if stelle.get("id", None) == stelle_id:
                    stelle_name = stelle.get("bezeichnung", None)
                    break
            
            if stelle_name is None:
                print(f"[CRON] Stelle des Bürgers mit Berufsverbot konnte nicht gefunden werden ({buerger_id})")
                continue

            # Überspringen, wenn die Stelle nicht unters Berufsverbot fällt
            if stelle_name not in berufsverbote:
                continue

            # Letzte Beschäftigung beenden
            lebenslauf[-1]["ende"] = datum
            buerger_daten["lebenslauf"] = lebenslauf

            # Nachricht ins Postfach schicken
            buerger_daten.setdefault("postfach", [])
            buerger_daten["postfach"].insert(0, {
                "sender": "System",
                "beschreibung": 'Deine letzte Beschäftigung wurde aufgrund deines Berufsverbots beendet.',
                "verlinkung": reverse('buerger/lebenslauf'), # Erstellt die entsprechende URL des Servers
                "status": True
            })
            
            # abspeichern
            with open(buerger_pfad, "w", encoding="utf-8") as f:
                f.write(json.dumps(buerger_daten, indent=2, ensure_ascii=False))
            
            # Stelle auf Unternehmensseite freigeben
            for stelle in stellen:
                if stelle.get("id", None) == stelle_id:
                    stelle["buerger"] = ""
                    stelle["besetzt"] = False
                    break
            unternehmen_daten["stellen"] = stellen

            # Nachricht ins Postfach schicken
            unternehmen_daten.setdefault("postfach", [])
            unternehmen_daten["postfach"].insert(0, {
                "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                "beschreibung": f'Der Bürger hat ein Berufsverbot für den Beruf bekommen, den er aktuell besitzt. Die Stelle "{stelle_name}" wurde wieder freigegeben.',
                "verlinkung": reverse('unternehmen/bewerber'), # Erstellt die entsprechende URL des Servers
                "status": True
            })

            # abspeichern
            with open(unternehmen_pfad, "w", encoding="utf-8") as f:
                f.write(json.dumps(unternehmen_daten, indent=2, ensure_ascii=False))
            print(f"[CRON] Stelle des Bürgers mit Berufsverbot wurde freigegeben ({buerger_id})")

        except Exception as e:
            print(f"[CRON] Beruf des Bürgers konnte nicht entfernt werden wegen eines Berufsverbots ({buerger_id}): {e}")



##############################
######### Dashboard ##########
##############################

def ermittle_dashboard_daten(buerger):
    lebenslauf = buerger.get("lebenslauf", [])
    bewerbungen = buerger.get("bewerbungen", [])
    postfach = buerger.get("postfach", [])

    #Aktuelle Beschäftigung ermitteln
    lebenslauf_moeglichkeiten = {
        "anstellung": "Anstellung",
        "duales_studium": "Duales Studium",
        "studium": "Studium",
        "ausbildung": "Ausbildung",
        "schueler": "Schüler",
        "rente": "Rente",
        "haft": "In Haft",
        "tot": "Tot",
        "arbeitslos": "Arbeitslos"
    }

    # Kai
    aktuelle_beschaeftigung = False
    if len(lebenslauf) > 0:
        aktuelle_beschaeftigung = {}
        letzer_eintrag = lebenslauf[-1]
        if letzer_eintrag.get("ende") is False or datetime.strptime(letzer_eintrag.get("ende"), "%Y-%m-%d") > datetime.now():
            aktuelle_beschaeftigung["art"] = lebenslauf_moeglichkeiten[letzer_eintrag.get("art")]
            beginn = datetime.strptime(letzer_eintrag.get("beginn"), "%Y-%m-%d")
            aktuelle_beschaeftigung["beginn"] = beginn.strftime("%d.%m.%Y")
            if letzer_eintrag.get("arbeitgeber"):
                with open(os.path.join(DATA_DIR, "unternehmen", f"{letzer_eintrag.get('arbeitgeber')}.json"), "r", encoding="utf-8") as f:
                    unternehmen_data = json.loads(f.read())
                aktuelle_beschaeftigung["arbeitgeber"] = unternehmen_data.get("name", "Unbekanntes Unternehmen")
                for stelle in unternehmen_data.get("stellen", []):
                    if stelle.get("id") == letzer_eintrag.get("stelle"):
                        aktuelle_beschaeftigung["stelle"] = stelle.get("bezeichnung", "Unbekannte Stelle")
                        break
            elif letzer_eintrag.get("bildungseinrichtung"):
                with open(os.path.join(DATA_DIR, "bildungseinrichtungen", f"{letzer_eintrag.get('bildungseinrichtung')}.json"), "r", encoding="utf-8") as f:
                    bildung_data = json.loads(f.read())
                aktuelle_beschaeftigung["bildungseinrichtung"] = bildung_data.get("name", "Unbekannte Bildungseinrichtung")

    # for art in lebenslauf_moeglichkeiten:
    #     for eintrag in lebenslauf:
    #         if eintrag.get("art") == art and eintrag.get("ende") is False:
    #             aktuelle_beschaeftigung = eintrag
    #             break
    #     if aktuelle_beschaeftigung:
    #         break

    #offene Bewerbungen
    offene_bewerbungen = [
        b for b in bewerbungen
        if b.get("status") in ("offen", "angebot")
    ]

    #ungelesene Nachrichten
    ungelesene_nachrichten = [
        n for n in postfach
        if n.get("status") is True
    ]

    return {
        "aktuelle_beschaeftigung": aktuelle_beschaeftigung,
        "offene_bewerbungen_anzahl": len(offene_bewerbungen),
        "ungelesene_nachrichten_anzahl": len(ungelesene_nachrichten),
    }

def setze_buergername_in_session(request, buerger_id):
    # Schon vorhanden? -> nix tun
    a = request.session.get("buerger_name")
    if a:
        return a

    name = str(buerger_id)

    try:
        r = requests.get(f"{API_Meldewesen_URL}/{buerger_id}", timeout = 5)
        data = r.json()
        vorname = data.get("vorname", "")
        if data.get("nachname_neu", None):
            nachname = data.get("nachname_neu", "")
        else:
            nachname = data.get("nachname_geburt", "")
        name = f"{vorname} {nachname}".strip()

        # r = requests.get(API_alle_Buerger_von_Meldewesen, timeout=3)
        # data = r.json()

        # personen = data.get("personen", [])
        # suche = next((p for p in personen if str(p.get("buerger_id")) == str(buerger_id)), None)

        # if suche:
        #     vorname = (suche.get("vorname") or "").strip()
        #     nachname = (suche.get("nachname_geburt") or "").strip()
        #     zusammengesetzt = (vorname + " " + nachname).strip()
        #     if zusammengesetzt:
        #         name = zusammengesetzt

    except Exception as e:
        print(f"[SESSION] Konnte Bürgernamen nicht laden ({buerger_id}): {e}")
        # text = str(e)

    request.session["buerger_name"] = name
    messages.success(request, "Willkommen zurück – mal schauen was es neues gibt!")
    return name

def session_anzeigen(request):
    return HttpResponse(str(dict(request.session)))


def load_or_create_buerger(request, buerger_id):        #hier nochmal ansetzen und auf API umstellen
    pfad = os.path.join(DATA_DIR, "buerger", f"{buerger_id}.json")

    # 1. Existiert die Datei?
    if os.path.exists(pfad):
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            messages.error(request, "Fehler beim Laden der Bürgerdatei – bitte Admin kontaktieren.")
            return None

    # 2. Datei existiert nicht → neuen Bürger anlegen
    buerger_daten = {
        "id": buerger_id,
        "lebenslauf": [],
        "bewerbungen": [],
        "postfach": []
    }

    # Ordner sicherstellen
    os.makedirs(os.path.dirname(pfad), exist_ok=True)

    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(buerger_daten, f, indent=2, ensure_ascii=False)

    messages.success(request, "Willkommen! Dein Bürgerprofil wurde automatisch angelegt 🥳")

    return buerger_daten


def buerger_dashboard(request):
    buerger_id = request.session.get("buerger_id")

    # Bürger-ID aus der Session holen, sonst Standard buerger0001 setzen
    if not buerger_id:
        buerger_id = "buerger0001"
        request.session["buerger_id"] = buerger_id

    setze_buergername_in_session(request, buerger_id)   # Name in Session setzen

    buerger_daten = load_or_create_buerger(request, buerger_id)

    dashboard = ermittle_dashboard_daten(buerger_daten)


    if request.method == "POST":
        nachricht = request.POST.get("nachricht")

        neuer_eintrag = {
            "sender": buerger_id,
            "beschreibung": nachricht,
            "status": True,
        }

        buerger_daten["postfach"].append(neuer_eintrag)
        
        admin_path = os.path.join(DATA_DIR, "admin", "admin.json")
        with open(admin_path, "r", encoding="utf-8") as f:
            admin_data = json.load(f)

        admin_data["postfach"].insert(0, neuer_eintrag)     #Eintrag in der admin.json ganz oben hinzufügen (Stelle 0)!

        with open(admin_path, "w", encoding="utf-8") as f:
            json.dump(admin_data, f, indent=2, ensure_ascii=False)

        messages.success(request, "Nachricht wurde erfolgreich gesendet!")

        return redirect("buerger/dashboard")
    
    return render(request, 'arbeitbildung/buerger/dashboard.html', {
        'role': 'buerger',
        'active_page': 'buerger_dashboard',
        'username': request.session.get("buerger_name", buerger_id),
        'buerger': buerger_daten,
        'aktuelle_beschaeftigung': dashboard["aktuelle_beschaeftigung"],
        'offene_bewerbungen_anzahl': dashboard["offene_bewerbungen_anzahl"],
        'ungelesene_nachrichten_anzahl': dashboard["ungelesene_nachrichten_anzahl"],
    })

##############################
######### Lebenslauf #########
##############################


# Hilfsfunktion wird bei den Sessions von Stefan deaktiviert!
def load_buerger_datei(buerger_id):
    dateiname = f"{buerger_id}.json"
    pfad = os.path.join(DATA_DIR, 'buerger', dateiname)

    try:
        with open(pfad, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[arbeitbildung] Datei nicht gefunden: {pfad}")
        return None
    except json.JSONDecodeError:
        print(f"[arbeitbildung] Fehler beim Lesen von JSON: {pfad}")
        return None

#Hilfsfunktion für die richtigen Daten m Lebenslauf
def lade_arbeitgeber_und_stelle(arbeitgeber_id, stelle_id):
    if not arbeitgeber_id:
        return None, None

    pfad = os.path.join(
        DATA_DIR,
        "unternehmen",
        f"{arbeitgeber_id}.json"
    )

    if not os.path.exists(pfad):
        return arbeitgeber_id, stelle_id  # Fallback: ID anzeigen

    try:
        with open(pfad, "r", encoding="utf-8") as f:
            unternehmen = json.load(f)

        arbeitgeber_name = unternehmen.get("name", arbeitgeber_id)

        stellen_name = None
        for stelle in unternehmen.get("stellen", []):
            if stelle.get("id") == stelle_id:
                stellen_name = stelle.get("bezeichnung")
                break

        return arbeitgeber_name, stellen_name or stelle_id

    except Exception as e:
        print("[ARBEITGEBER_LOOKUP]", e)
        return arbeitgeber_id, stelle_id


def buerger_lebenslauf_download(request):
    # Bürger-ID aus Session oder Fallback
    buerger_id = request.session.get('buerger_id', 'buerger0001')

    buerger_daten = load_buerger_datei(buerger_id)
    if not buerger_daten:
        messages.error(request, "Die Lebenslaufdaten konnten nicht heruntergeladen werden.")
        return redirect('buerger_lebenslauf')

    # Nur den Lebenslauf-Teil exportieren
    lebenslauf = buerger_daten.get('lebenslauf', [])

    # JSON-String erstellen (schön formatiert)
    json_text = json.dumps(lebenslauf, ensure_ascii=False, indent=2)

    # HTTP-Response als Download
    filename = f"lebenslauf_{buerger_id}.json"
    response = HttpResponse(json_text, content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    return response

def ermittle_buerger_stammdaten(buerger_id):

    daten = {
        "name": "Unbekannt",
        "adresse": "Adresse nicht hinterlegt",
        "geburtsdatum": "Unbekannt"
    }

    try:
        r = requests.get(f"{API_Meldewesen_URL}/{buerger_id}", timeout = 5)
        data = r.json()

        # personen = api_daten.get("personen", [])
        # person = next(
        #     (p for p in personen if str(p.get("buerger_id")) == str(buerger_id)),
        #     None
        # )

        # if not person:
        #     return daten

        # Name
        # vorname = (person.get("vorname") or "").strip()
        # nachname = (person.get("nachname_geburt") or "").strip()
        vorname = data.get("vorname", "")
        if data.get("nachname_neu", None):
            nachname = data.get("nachname_neu", "")
        else:
            nachname = data.get("nachname_geburt", "")
        daten["name"] = f"{vorname} {nachname}".strip()

        # Adresse (optional!)
        # adresse = person.get("adresse")
        # if adresse:
        #     strasse = adresse.get("straße_hausnummer", "").strip()
        #     plz_ort = adresse.get("plz_ort", "").strip()

        #     if strasse or plz_ort:
        #         daten["adresse"] = f"{strasse}, {plz_ort}".strip(", ")
        if data.get("wohnsitz"):
            adresse = data.get("wohnsitz")
            strasse = adresse.get("straße_hausnummer", "").strip()
            plz_ort = adresse.get("plz_ort", "").strip()
            daten["adresse"] = f"{strasse}, {plz_ort}"

        geburtsdatum = data.get("geburtsdatum", "")
        geburtsdatum = datetime.strptime(geburtsdatum, "%Y-%m-%d")
        if geburtsdatum:
            daten["geburtsdatum"] = geburtsdatum.strftime("%d.%m.%Y")
            # daten["geburtsdatum"] = datetime.strptime(geburtsdatum, "%d-%m-%Y").strftime("%Y-%m-%d")

    except Exception as e:
        print(f"[STAMMDATEN] Fehler bei Bürger {buerger_id}: {e}")

    return daten

def entferne_buerger_aus_schule(buerger_id, schule_id):
    if not schule_id:
        return False

    pfad = os.path.join(DATA_DIR, "bildungseinrichtungen", f"{schule_id}.json")
    if not os.path.exists(pfad):
        print(f"[ARBEITSLOS] Schule nicht gefunden: {pfad}")
        return False

    try:
        with open(pfad, "r", encoding="utf-8") as f:
            schule = json.load(f)

        vorher = len(schule.get("schueler", []))
        schule["schueler"] = [
            s for s in schule.get("schueler", [])
            if str(s.get("id")) != str(buerger_id)
        ]
        nachher = len(schule.get("schueler", []))

        buerger_name = ermittle_buerger_stammdaten(buerger_id).get("name", buerger_id)

        if nachher != vorher:
            schule.setdefault("postfach", [])
            schule["postfach"].insert(0, {
                "sender": buerger_name,
                "beschreibung": f"Schüler hat sich abgemeldet: {buerger_name}",
                "verlinkung": "/bildungseinrichtungen/schueler",
                "status": True
            })

            with open(pfad, "w", encoding="utf-8") as f:
                json.dump(schule, f, indent=2, ensure_ascii=False)

            return True

    except Exception as e:
        print(f"[ARBEITSLOS] Fehler beim Entfernen aus Schule {schule_id}: {e}")

    return False


def gebe_unternehmensstelle_frei(buerger_id, unternehmen_id, stelle_id):
    if not (unternehmen_id and stelle_id):
        return False

    pfad = os.path.join(DATA_DIR, "unternehmen", f"{unternehmen_id}.json")
    if not os.path.exists(pfad):
        print(f"[ARBEITSLOS] Unternehmen nicht gefunden: {pfad}")
        return False

    try:
        with open(pfad, "r", encoding="utf-8") as f:
            u = json.load(f)

        stelle_name = None
        changed = False

        for stelle in u.get("stellen", []):
            if str(stelle.get("id")) == str(stelle_id) and str(stelle.get("buerger")) == str(buerger_id):
                stelle["buerger"] = ""
                stelle["besetzt"] = False
                stelle_name = stelle.get("bezeichnung", stelle_id)
                changed = True
                break

        if changed:
            u.setdefault("postfach", [])
            u["postfach"].insert(0, {
                "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                "beschreibung": f"Mitarbeiter abgemeldet (arbeitslos). Stelle '{stelle_name}' ({stelle_id}) wurde freigegeben.",
                "verlinkung": "/unternehmen/bewerber",
                "status": True
            })

            with open(pfad, "w", encoding="utf-8") as f:
                json.dump(u, f, indent=2, ensure_ascii=False)

            return True

    except Exception as e:
        print(f"[ARBEITSLOS] Fehler beim Freigeben der Stelle {unternehmen_id}/{stelle_id}: {e}")

    return False

#--------------------Bildungseinrichtung letzter Eintrag beenden, wenn man sich in der Schule anmeldet -----------------------------------

def beende_letzten_aktiven_lebenslauf_eintrag(lebenslauf_liste,buerger_id,heutiges_datum):

    letzter_aktiver_eintrag = None

    # Lebenslauf rückwärts durchgehen → aktuellster Eintrag zuerst
    for lebenslauf_eintrag in reversed(lebenslauf_liste):

        # Enddatum des Eintrags holen
        enddatum = lebenslauf_eintrag.get("ende")

        # Fall 1: Eintrag ist noch offen (ende == False)
        if enddatum is False:
            letzter_aktiver_eintrag = lebenslauf_eintrag
            break

        # Fall 2: Enddatum ist ein String (Datum)
        # isinstance schützt davor, .strip() auf None oder False auszuführen
        if isinstance(enddatum, str) and enddatum.strip():
            try:
                # Enddatum in echtes Datum umwandeln
                enddatum_dt = datetime.strptime(enddatum, "%Y-%m-%d").date()
                heute_dt = datetime.strptime(heutiges_datum, "%Y-%m-%d").date()

                # Wenn der Eintrag noch läuft (Enddatum heute oder später)
                if enddatum_dt >= heute_dt:
                    letzter_aktiver_eintrag = lebenslauf_eintrag
                    break

            except Exception:
                # Falls das Datum kaputt formatiert ist → ignorieren
                pass

    # Wenn ein aktiver Eintrag gefunden wurde → beenden
    if letzter_aktiver_eintrag:
        # letzter_aktiver_eintrag["ende"] = heutiges_datum
        if len(lebenslauf_liste) > 0:
            lebenslauf_liste[-1]["ende"] = heutiges_datum
        else:
            lebenslauf_liste = []

        # Falls der Eintrag zu einer Bildungseinrichtung gehört dann dort abmelden
        bildungseinrichtungs_id = letzter_aktiver_eintrag.get("bildungseinrichtung")
        if bildungseinrichtungs_id:
            entferne_buerger_aus_schule(buerger_id, bildungseinrichtungs_id)

        # Falls der Eintrag zu einem Arbeitgeber gehört dann Stelle freigeben
        arbeitgeber_id = letzter_aktiver_eintrag.get("arbeitgeber")
        stellen_id = letzter_aktiver_eintrag.get("stelle")
        if arbeitgeber_id and stellen_id:
            gebe_unternehmensstelle_frei(
                buerger_id,
                arbeitgeber_id,
                stellen_id
            )

        return lebenslauf_liste

#-------------------------------------------------------------------------------------

def buerger_lebenslauf(request):
    # Bürger-ID aus der Session holen, sonst Standard buerger0001 setzen
    buerger_id = request.session.get('buerger_id')
    if not buerger_id:
        buerger_id = 'buerger0001'   # Testbürger, später einfach entfernen
        request.session['buerger_id'] = buerger_id

    stammdaten = ermittle_buerger_stammdaten(buerger_id)
    # Name aus session laden
    buerger_name = request.session.get("buerger_name", "Unbekannt")

    # JSON-Datei dieses Bürgers laden
    buerger_daten = load_buerger_datei(buerger_id)

    if not buerger_daten:
        messages.error(request, "Die Lebenslaufdaten konnten nicht geladen werden.")
        lebenslauf = []
    else:
        lebenslauf = buerger_daten.get('lebenslauf', [])

    #statt IDs in Lebenslauf Namen arbeitgeber + stelle
    for eintrag in lebenslauf:
        if eintrag.get("arbeitgeber") and eintrag.get("stelle"):
            arbeitgeber_name, stellen_name = lade_arbeitgeber_und_stelle(
                eintrag["arbeitgeber"],
                eintrag["stelle"]
            )

            eintrag["arbeitgeber_name"] = arbeitgeber_name
            eintrag["stellen_name"] = stellen_name


    if request.method == "POST":
        action = request.POST.get("action")

        # Lebenslauf-Eintrag vorzeitig beenden / kündigen
        if action == "lebenslauf_beenden":
            index = request.POST.get("index")

            # nicht nur None, sondern auch "" abfangen
            if not index or not str(index).strip().isdigit():
                messages.error(request, "Ungültiger Lebenslauf-Eintrag (Index fehlt).")
                return redirect("buerger/lebenslauf")

            index = int(index)
            index = len(lebenslauf) - 1 - index
            pfad_buerger = os.path.join(DATA_DIR, "buerger", f"{buerger_id}.json")

            with open(pfad_buerger, "r", encoding="utf-8") as f:
                buerger_daten = json.load(f)

            lebenslauf = buerger_daten.get("lebenslauf", [])

            #for position, eintrag in enumerate(lebenslauf):
            #    eintrag["position_im_lebenslauf"] = position


            if index < 0 or index >= len(lebenslauf):
                messages.error(request, "Lebenslauf-Eintrag nicht gefunden.")
                return redirect("buerger/lebenslauf")

            eintrag = lebenslauf[index]

            arbeitgeber_id = eintrag.get("arbeitgeber")
            stelle_id = eintrag.get("stelle")
            bildungs_id = eintrag.get("bildungseinrichtung")

            heute = datetime.now().strftime("%Y-%m-%d")
            ende = eintrag.get("ende")

            ist_aktiv = (ende is False) or (isinstance(ende, str) and ende.strip() and ende >= heute)

            if ist_aktiv:
                eintrag["ende"] = heute
                messages.success(request, "Das Verhältnis wurde erfolgreich beendet.")
            else:
                messages.info(request, "Dieser Eintrag ist bereits beendet.")

            buerger_daten["lebenslauf"] = lebenslauf

            with open(pfad_buerger, "w", encoding="utf-8") as f:
                json.dump(buerger_daten, f, indent=2, ensure_ascii=False)


            # Arbeitgeber-Stelle freigeben
            if arbeitgeber_id and stelle_id:
                pfad_unternehmen = os.path.join(
                    DATA_DIR,
                    "unternehmen",
                    f"{arbeitgeber_id}.json"
                )

                if os.path.exists(pfad_unternehmen):
                    with open(pfad_unternehmen, "r", encoding="utf-8") as f:
                        unternehmen = json.load(f)

                    for stelle in unternehmen.get("stellen", []):
                        if stelle.get("id") == stelle_id:
                            stelle["buerger"] = ""
                            stelle["besetzt"] = False
                            stelle_name = stelle.get("bezeichnung", stelle_id)
                            break

                    #Postfach-Eintrag
                    unternehmen.setdefault("postfach", [])
                    unternehmen["postfach"].insert(0, {
                        "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                        "beschreibung": f"Hat das Verhältnis für Stelle {stelle_name} ({stelle_id}) beendet. Stelle ist wieder frei.",
                        "status": True
                    })

                    with open(pfad_unternehmen, "w", encoding="utf-8") as f:
                        json.dump(unternehmen, f, indent=2, ensure_ascii=False)

            # Bildungseinrichtungs-Stelle freigeben
            if bildungs_id:
                pfad_bildungseinrichtung = os.path.join(
                    DATA_DIR,
                    "bildungseinrichtungen",
                    f"{bildungs_id}.json"
                )

                if os.path.exists(pfad_bildungseinrichtung):
                    with open(pfad_bildungseinrichtung, "r", encoding="utf-8") as f:
                        bildungseinrichtung = json.load(f)

                    for schueler in bildungseinrichtung.get("schueler", []):
                        if str(schueler.get("id")) == str(buerger_id):
                            bildungseinrichtung["schueler"].remove(schueler)
                            break

                    #Postfach-Eintrag
                    bildungseinrichtung.setdefault("postfach", [])
                    bildungseinrichtung["postfach"].insert(0, {
                        "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                        "beschreibung": f"Hat das Verhältnis für Bildungseinrichtung {bildungs_id} beendet. Schüler wurde abgemeldet.",
                        "status": True
                    })

                    with open(pfad_bildungseinrichtung, "w", encoding="utf-8") as f:
                        json.dump(bildungseinrichtung, f, indent=2, ensure_ascii=False)

            return redirect("buerger/lebenslauf")
        

        elif action == "arbeitslos_melden":
            pfad_buerger = os.path.join(DATA_DIR, "buerger", f"{buerger_id}.json")
            heute = datetime.now().strftime("%Y-%m-%d")

            with open(pfad_buerger, "r", encoding="utf-8") as f:
                buerger_daten = json.load(f)

            lebenslauf = buerger_daten.get("lebenslauf", [])
            buerger_daten.setdefault("postfach", [])

            # Schon arbeitslos?
            if lebenslauf and lebenslauf[-1].get("art") == "arbeitslos" and lebenslauf[-1].get("ende") is False:
                messages.info(request, "Du bist bereits als arbeitslos gemeldet.")
                return redirect("buerger/lebenslauf")

            # Letzten relevanten Eintrag finden
            aktive_arten = ["anstellung", "ausbildung", "studium", "duales_studium", "schueler"]

            letzter_aktiver = None
            for eintrag in reversed(lebenslauf):
                if eintrag.get("art") not in aktive_arten:
                    continue

                ende = eintrag.get("ende", None)

                if ende is False:
                    letzter_aktiver = eintrag
                    break

                if isinstance(ende, str) and ende.strip():
                    try:
                        ende_dt = datetime.strptime(ende, "%Y-%m-%d").date()
                        heute_dt = datetime.strptime(heute, "%Y-%m-%d").date()
                        if ende_dt >= heute_dt:
                            letzter_aktiver = eintrag
                            break
                    except Exception:
                        pass

            # Aktiven Eintrag beenden
            if letzter_aktiver:
                letzter_aktiver["ende"] = heute

                # Falls Schule/Bildung: aus Bildungseinrichtung entfernen
                bild_id = letzter_aktiver.get("bildungseinrichtung")
                if bild_id:
                    entferne_buerger_aus_schule(buerger_id, bild_id)

                # Falls Arbeitgeber/Stelle: Stelle freigeben
                arbeitgeber_id = letzter_aktiver.get("arbeitgeber")
                stelle_id = letzter_aktiver.get("stelle")
                if arbeitgeber_id and stelle_id:
                    gebe_unternehmensstelle_frei(buerger_id, arbeitgeber_id, stelle_id)


            # Arbeitslos-Eintrag hinzufügen
            lebenslauf.append({
                "beginn": heute,
                "ende": False,
                "art": "arbeitslos",
                "bildungseinrichtung": False,
                "arbeitgeber": False,
                "stelle": False,
                "zeugnis": {}
            })

            buerger_daten["lebenslauf"] = lebenslauf

            # Postfach Bürger
            buerger_daten["postfach"].insert(0, {
                "sender": "System",
                "beschreibung": "Du wurdest als arbeitslos gemeldet. Lebenslauf und Register wurden aktualisiert.",
                "status": True
            })

            # Admin-Postfach
            admin_path = os.path.join(DATA_DIR, "admin", "admin.json")
            try:
                with open(admin_path, "r", encoding="utf-8") as f:
                    admin_data = json.load(f)
            except Exception:
                admin_data = {"postfach": []}

            admin_data.setdefault("postfach", [])
            admin_data["postfach"].insert(0, {
                "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                "beschreibung": "Bürger hat sich arbeitslos gemeldet. Schule/Unternehmen wurden ggf. bereinigt.",
                "status": True
            })

            # Speichern
            with open(pfad_buerger, "w", encoding="utf-8") as f:
                json.dump(buerger_daten, f, indent=2, ensure_ascii=False)

            with open(admin_path, "w", encoding="utf-8") as f:
                json.dump(admin_data, f, indent=2, ensure_ascii=False)

            messages.success(request, "Arbeitslosmeldung wurde gespeichert.")
            return redirect("buerger/lebenslauf")




 #----------------------------------------------------------------------------------------------------
    # Bildungseinrichtung 
    # Filter variablen 
    filter_schulen_kennwort = ""
    filter_schulen_art = "all"

    if request.method == "POST":
        filter_schulen_kennwort = request.POST.get("filter_schulen_kennwort", "").strip()
        filter_schulen_art = request.POST.get("filter_schulen_art", "all").strip()
        action = request.POST.get("action")
       
       #Anmelung bei Bildungseinrichtung 
        if action == "anmeldung":
            schule_id = request.POST.get("schule_id")
         
            if not schule_id:
                messages.error(request, "Keine Schule ausgewählt.")
                return redirect("buerger/lebenslauf")

            pfad_schule = os.path.join(DATA_DIR, "bildungseinrichtungen", f"{schule_id}.json")
            pfad_buerger = os.path.join(DATA_DIR, "buerger", f"{buerger_id}.json")

            if not os.path.exists(pfad_schule):
                messages.error(request, "Ungültige Bildungseinrichtung.")
                return redirect("buerger/lebenslauf")
            
            # Schule laden
            with open(pfad_schule, "r", encoding="utf-8") as f:
                schule = json.load(f)
        
            # Plätze prüfen
            plaetze_gesamt = int(schule.get("plaetze_gesamt", 0))
            belegte_plaetze = len(schule.get("schueler", []))

            if belegte_plaetze >= plaetze_gesamt:
                messages.error(request, "Keine freien Plätze mehr.")
                return redirect("buerger/lebenslauf")

            # Schülerliste holen oder leere Liste erstellen
            schueler_liste = schule.get("schueler")
            if schueler_liste is None:
                schueler_liste = []
                schule["schueler"] = schueler_liste

            # Doppelanmeldung verhindern
            bereits_angemeldet = False
            for schueler in schueler_liste:
                if schueler["id"] == buerger_id:
                    bereits_angemeldet = True
                    break

            if bereits_angemeldet:
                messages.info(request, "Du bist bereits angemeldet.")
                return redirect("buerger/lebenslauf")

            # Bürger zur Schülerliste hinzufügen
            schueler_liste.append({
                "id": buerger_id
                })

            # Lebenslauf-Liste holen oder erstellen
            lebenslauf_liste = buerger_daten.get("lebenslauf")
            if lebenslauf_liste is None:
                lebenslauf_liste = []
                #buerger_daten["lebenslauf"] = lebenslauf_liste

            # Heutiges Datum
            heutiges_datum = datetime.now().strftime("%Y-%m-%d")

            # Letzten aktiven Eintrag beenden, Funktion von oben aufrufen 
            
            lebenslauf_liste = beende_letzten_aktiven_lebenslauf_eintrag(lebenslauf_liste,buerger_id,heutiges_datum)
            if lebenslauf_liste is None:
                lebenslauf_liste = []
            # Aufenthalt in Bildungseinrichtung mit dauer berechnen 

            beginn = datetime.now()

            # Dauer der Schule in Jahren aus der Schul-JSON-Datei
            try:
                dauer_jahre = int(schule.get("dauer", 0))
            except (TypeError, ValueError):
                dauer_jahre = 0

            # Ende berechnen
            ende = beginn.replace(year=beginn.year + dauer_jahre).strftime("%Y-%m-%d")

            # Neuen Lebenslauf-Eintrag hinzufügen
            lebenslauf_liste.append({
                "beginn": beginn.strftime("%Y-%m-%d"),
                "ende": ende,
                "art": "schueler",
                "bildungseinrichtung": schule_id,
                "arbeitgeber": False,
                "stelle": False,
                "zeugnis": {}
            })

           # Neue Nachricht ins Postfach der Schule einfügen
            postfach = schule.get("postfach")
            if postfach is None:
                postfach = []
                schule["postfach"] = postfach

            postfach.insert(0,({
                "sender": "System",
                "beschreibung": f"Neuer Schüler: {buerger_name}",
                "verlinkung": f"/bildungseinrichtungen/schueler",
                "status": True
            }))

            buerger_daten["lebenslauf"] = lebenslauf_liste

            # Speichern
            with open(pfad_schule, "w", encoding="utf-8") as f:
                json.dump(schule, f, indent=2, ensure_ascii=False)

            with open(pfad_buerger, "w", encoding="utf-8") as f:
                json.dump(buerger_daten, f, indent=2, ensure_ascii=False)

            messages.success(request, "Erfolgreich angemeldet 🎓")
            return redirect("buerger/lebenslauf")

    schulen_liste = []

    # Schulen als Dictionary (ID → Objekt) für Zeugnisse
    schulen_dict = {schule["id"]: schule for schule in schulen_liste}


    # Bildungseinrichtungen
    #Schulen in der Tabelle anziegen lassen
    # Alle JSON-Dateien im Ordner durchgehen
    DATA_SCHULEN = '/var/www/django-project/arbeitbildung/data/bildungseinrichtungen'
    


    CACHE_FILE = os.path.join(DATA_SCHULEN, "geocode_cache.json")

    geocode_cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            geocode_cache = json.load(f)

    geolocator = Nominatim(user_agent = "arbeitbildung_app")    

    for datei in os.listdir(DATA_SCHULEN):
        if datei.lower().endswith(".json") and datei.startswith("b"):
            pfad = os.path.join(DATA_SCHULEN, datei)

            with open(pfad, "r", encoding="utf-8") as f:
                schule = json.load(f)

                # Nur aktive Schulen berücksichtigen
                if not schule.get("aktiv", False):
                    continue

                # Freie Plätze berechnen
                belegte_plaetze = len(schule.get("schueler", []))

                # plaetze_gesamt sicher in int umwandeln
                plaetze_gesamt = schule.get("plaetze_gesamt", 0)
                try:
                    plaetze_gesamt = int(plaetze_gesamt)
                except (TypeError, ValueError):
                    plaetze_gesamt = 0

                schule["plaetze_frei"] = max(plaetze_gesamt - belegte_plaetze, 0)

                adresse = schule.get("adresse", "")

                if adresse in geocode_cache:
                    schule["coords"] = geocode_cache[adresse]
                else:
                    try:
                        location = geolocator.geocode(adresse, timeout=10)
                    except Exception as e:
                        location = None

                    if location:
                        coords = {"lat": location.latitude, "lng": location.longitude}
                        schule["coords"] = coords
                        geocode_cache[adresse] = coords
                    else:
                        schule["coords"] = None

                schulen_liste.append(schule)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(geocode_cache, f, ensure_ascii=False, indent=2)


    # Schulen werden nach Name sortiert
    schulen_liste.sort(key=lambda s: s.get("name", ""))
    
    
    
   # Filter nach Kennwort, Name der Schule
    if filter_schulen_kennwort:
        suchbegriff = filter_schulen_kennwort.lower()
        gefilterte_schulen = []
        for schule in schulen_liste:
            if suchbegriff in schule.get("name", "").lower():
                gefilterte_schulen.append(schule)
        schulen_liste = gefilterte_schulen

    # Filter nach Schulart
    if filter_schulen_art != "all":
        gefilterte_schulen = []
        for schule in schulen_liste:
            if schule.get("schulart") == filter_schulen_art:
                gefilterte_schulen.append(schule)
        schulen_liste = gefilterte_schulen

    try:
        buerger_location = geolocator.geocode(stammdaten['adresse'], timeout = 10)
        buerger_coords = [ buerger_location.longitude, buerger_location.latitude ]
    except Exception as e:
        buerger_coords = None   
#------------------------------------Alters Logik bei SChulen ----------------------------------------
    # Alter berechnen des Bürgers 
    geburtsdatum = stammdaten.get("geburtsdatum")  # Format: YYYY-MM-DD
    buerger_alter = None
    if geburtsdatum:
        try:
            try:
                geburtsdatum_dt = datetime.strptime(geburtsdatum, "%Y-%m-%d").date()
            except ValueError:
                geburtsdatum_dt = datetime.strptime(geburtsdatum, "%d.%m.%Y").date()
            heute = datetime.now().date()
            buerger_alter = heute.year - geburtsdatum_dt.year - ((heute.month, heute.day) < (geburtsdatum_dt.month, geburtsdatum_dt.day))
        except Exception:
            buerger_alter = None
    
    # Prüfen, ob Bürger aktuell in einer Schule ist
     
    # Prüfen, ob Bürger aktuell in einer Schule ist
    ist_in_schule = False
    if len(lebenslauf) > 0:
        letzter_eintrag = lebenslauf[-1]
        if letzter_eintrag.get("art") == "schueler":
            ende_str = letzter_eintrag.get("ende")
            if isinstance(ende_str, str) and ende_str.strip():
                try:
                    ende_dt = datetime.strptime(ende_str, "%Y-%m-%d").date()
                    heute = datetime.now().date()
                    if heute < ende_dt:
                        ist_in_schule = True
                except Exception:
                    pass
            elif ende_str is False:
                ist_in_schule = True
    # for eintrag in reversed(lebenslauf):
    #     if eintrag.get("art") == "schueler":
    #         continue
    #     beginn_dt = datetime.strptime(eintrag.get("beginn"), "%Y-%m-%d").date()
    #     ende_str = eintrag.get("ende")

    #     #Wenn das Ende KEIN gültiges Datums-String ist, dann überspringt man diesen Schuleintrag.
    #     if not isinstance(ende_str, str) or ende_str in ("", None, False):
    #         continue

    #     ende_dt = datetime.strptime(ende_str, "%Y-%m-%d").date()

    #     if beginn_dt <= heute <= ende_dt:
    #         ist_in_schule = True
    #         break
                
    # Schulen nach Alter filtern
    if buerger_alter is not None and ist_in_schule == False:
        gefilterte_schulen = []
        for schule in schulen_liste:
            art = schule.get("schulart", "")
            if art == "Kindergarten" and 0 <= buerger_alter <= 7:
                gefilterte_schulen.append(schule)
            elif art == "Grundschule" and 5 <= buerger_alter <= 12:
                gefilterte_schulen.append(schule)
            elif art in ["Hauptschule", "Realschule", "Gymnasium", "Berufsschule"] and 9 <= buerger_alter <= 21:
                gefilterte_schulen.append(schule)
        schulen_liste = gefilterte_schulen

#-------------------------------------------------------------------------------------------------------

    deaktivierte_arten = ["arbeitslos", "tot", "haft", "rente"]


    # An Template übergeben
    return render(request, 'arbeitbildung/buerger/lebenslauf.html', {
        'role': 'buerger',
        'active_page': 'buerger_lebenslauf',
        'username': request.session.get("buerger_name", buerger_id),
        'buerger_id': buerger_id,
        'lebenslauf': lebenslauf,
        'schulen': schulen_liste,
        'schulen_dict': schulen_dict,
        'schulen_json': json.dumps(schulen_liste),
        'filter_schulen_kennwort': filter_schulen_kennwort,
        'filter_schulen_art': filter_schulen_art,
        'stammdaten': stammdaten,
        'buerger_coords': buerger_coords,
        'buerger_alter': buerger_alter,
        'ist_in_schule': ist_in_schule,
        'deaktivierte_arten': deaktivierte_arten,

    })

##############################
########## Jobbörse ##########
##############################

def get_alter(buerger_id):
    try:
        r = requests.get(f"{API_Meldewesen_URL}/{buerger_id}", timeout = 5)
        data = r.json()
        geburtsdatum_data = data.get("geburtsdatum", "")
        try:
            geburtsdatum = datetime.strptime(geburtsdatum_data, "%Y-%m-%d")
        except ValueError:
            geburtsdatum = datetime.strptime(geburtsdatum_data, "%d.%m.%Y")
        geburtsdatum = datetime.strptime(geburtsdatum_data, "%Y-%m-%d")
        heute = datetime.now()
        alter = heute.year - geburtsdatum.year - ((heute.month, heute.day) < (geburtsdatum.month, geburtsdatum.day)) # Wenn Tag und Monat noch nicht erreicht (Vergleich beider Tuples) -> - 1 Jahr (True = 1, False = 0)
        return alter
    except Exception as e:
        print(f"API-Fehler beim Überprüfen des Alters für {buerger_id}: {e}")
        return None

def buerger_jobboerse(request):
  
    buerger_id = request.session.get('buerger_id')
    if not buerger_id:
        buerger_id = 'buerger0001'   #! Testbürger, später einfach entfernen
        request.session['buerger_id'] = buerger_id

    filter_jobangebote_kennwortsuche = ""
    filter_jobangebote_bereich = "all"
    filter_ausbildungen_kennwortsuche = ""
    filter_ausbildungen_bereich = "all"
    filter_studium_kennwortsuche = ""
    filter_studium_bereich = "all"
    filter_studium_dual = "all"

    if request.method == "POST":
        filter_jobangebote_kennwortsuche = request.POST.get("filter_jobangebote_kennwortsuche", "").strip()
        filter_jobangebote_bereich = request.POST.get("filter_jobangebote_bereich", "all").strip()
        filter_ausbildungen_kennwortsuche = request.POST.get("filter_ausbildungen_kennwortsuche", "").strip()
        filter_ausbildungen_bereich = request.POST.get("filter_ausbildungen_bereich", "all").strip()
        filter_studium_kennwortsuche = request.POST.get("filter_studium_kennwortsuche", "").strip()
        filter_studium_bereich = request.POST.get("filter_studium_bereich", "all").strip()
        filter_studium_dual = request.POST.get("filter_studium_dual", "all").strip()
        action = request.POST.get("action", "")

        if action == "bewerben":
            unternehmen_id = request.POST.get("unternehmen_id", "").strip()
            stelle_id = request.POST.get("stelle_id", "").strip()

            if not unternehmen_id or not stelle_id:
                messages.error(request, "Ungültige Bewerbung - Stellen-ID oder Unternehmen-ID sind fehlerhaft.")

            else:
                pfad_buerger = os.path.join(DATA_DIR, "buerger", f"{buerger_id}.json")

                with open(pfad_buerger, "r", encoding = "utf-8") as f:
                    buerger_daten = json.load(f)

                neue_bewerbung = {
                    "bewerbungsdatum": datetime.now().strftime("%Y-%m-%d"),
                    "rückmeldedatum": False,
                    "arbeitgeber": unternehmen_id,
                    "stelle": stelle_id,
                    "status": "offen"
                }

                buerger_daten.setdefault("bewerbungen", []) # Falls "bewerbungen" nicht existiert, wird die Liste erstellt
                buerger_daten["bewerbungen"].append(neue_bewerbung)

                with open(pfad_buerger, "w", encoding = "utf-8") as f:
                    json.dump(buerger_daten, f, indent = 2, ensure_ascii = False)

                pfad_unternehmen = os.path.join(DATA_DIR, "unternehmen", f"{unternehmen_id}.json")

                with open(pfad_unternehmen, "r", encoding = "utf-8") as f:
                    unternehmen_daten = json.load(f)

                neue_bewerbung_unternehmen = {
                    "bewerber": buerger_id,
                    "stelle": stelle_id,
                    "bewerbungsdatum": datetime.now().strftime("%Y-%m-%d"),
                    "rückmeldedatum": False,
                    "status": "offen"
                }

                unternehmen_daten.setdefault("bewerbungen", [])
                unternehmen_daten["bewerbungen"].append(neue_bewerbung_unternehmen)
                unternehmen_daten.setdefault("postfach", [])

                stelle_name = next( # Nimmt den ersten Eintrag der Liste, der auf die Bedingung passt
                    (stelle.get("bezeichnung") for stelle in unternehmen_daten.get("stellen", []) if stelle.get("id") == stelle_id),
                    "Unbekannte Stelle"
                )

                unternehmen_daten["postfach"].insert(0, { # Setzt den Eintrag an die erste Stelle der Liste
                    "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                    "beschreibung": f"Neue Bewerbung für Stelle {stelle_name} ({stelle_id}).",
                    "verlinkung": reverse('unternehmen/bewerber'), # Erstellt die entsprechende URL des Servers
                    "status": True
                })

                with open(pfad_unternehmen, "w", encoding = "utf-8") as f:
                    json.dump(unternehmen_daten, f, indent = 2, ensure_ascii = False)

                messages.success(request, "Deine Bewerbung wurde erfolgreich eingereicht!")
        
    kind_alter = get_kind_alter()
    unternehmen_dir = os.path.join(DATA_DIR, "unternehmen")
    buerger_dir = os.path.join(DATA_DIR, "buerger")
    offene_stellen = []

    # Art Beschäftigung heraussuchen
    aktuelle_beschaeftigung = None
    with open(os.path.join(buerger_dir, f"{buerger_id}.json"), "r", encoding = "utf-8") as f:
        buerger_daten = json.load(f)
        lebenslauf = buerger_daten.get("lebenslauf", [])
        if len(lebenslauf) > 0:
            if lebenslauf[-1].get("ende", False) is False and lebenslauf[-1].get("art", False) in ["tot", "rente", "haft"]:
                aktuelle_beschaeftigung = lebenslauf[-1]["art"]
    if aktuelle_beschaeftigung is None:
        alter = get_alter(buerger_id)
        if alter is not None and alter < kind_alter:
            aktuelle_beschaeftigung = "kind"
        elif check_berufsverbot(buerger_id):
            aktuelle_beschaeftigung = "berufsverbot"

    unternehmen_cache_file = os.path.join(unternehmen_dir, "geocode_cache.json")
    unternehmen_geocode_cache = {}
    geolocator = Nominatim(user_agent = "arbeitbildung_app")

    if os.path.exists(unternehmen_cache_file):
        with open(unternehmen_cache_file, "r", encoding="utf-8") as f:
            unternehmen_geocode_cache = json.load(f)

    offene_bewerbungen = []
    with open(os.path.join(buerger_dir, f"{buerger_id}.json"), "r", encoding = "utf-8") as f:
        buerger_daten = json.load(f)                
        for bewerbung in buerger_daten.get("bewerbungen", []):
            if bewerbung.get("status", "") in ["offen", "angebot"]:
                offene_bewerbungen.append({
                    "unternehmen_id": bewerbung.get("arbeitgeber", ""),
                    "stelle_id": bewerbung.get("stelle", "")
                })

    for file in os.listdir(unternehmen_dir):
        if not file.endswith(".json") or not file.startswith("u"):
            continue
        with open(os.path.join(unternehmen_dir, file), "r", encoding = "utf-8") as f:
            unternehmen = json.load(f)
            if not unternehmen.get("aktiv", False):
                continue
            stellen = unternehmen.get("stellen", [])
            adresse = unternehmen.get("adresse", "")
            if len(stellen) > 0:
                if adresse not in unternehmen_geocode_cache:
                    try:
                        location = geolocator.geocode(adresse, timeout=10)
                    except Exception as e:
                        location = None
                    if location:
                        coords = {"lat": location.latitude, "lng": location.longitude}
                        unternehmen_geocode_cache[adresse] = coords
            for stelle in stellen:
                if stelle.get("aktiv", False) and not stelle.get("besetzt", False):
                    bereits_beworben = any(
                        b["unternehmen_id"] == unternehmen.get("id") and b["stelle_id"] == stelle.get("id")
                        for b in offene_bewerbungen
                    )
                    offene_stellen.append({
                        "unternehmen_id": unternehmen.get("id"),
                        "unternehmen_name": unternehmen.get("name"),
                        "unternehmen_adresse": adresse,
                        "unternehmen_coords": unternehmen_geocode_cache.get(adresse),
                        "stelle_id": stelle.get("id"),
                        "bezeichnung": stelle.get("bezeichnung"),
                        "beschreibung": stelle.get("beschreibung"),
                        "bereiche": stelle.get("bereiche"),
                        "voraussetzungen": stelle.get("voraussetzungen"),
                        "gehalt": stelle.get("gehalt"),
                        "gehalt_str": f"{stelle.get("gehalt"):,}".replace(",", "."),
                        "art": stelle.get("art"),
                        "dauer": stelle.get("dauer"),
                        "beworben": bereits_beworben
                    })

    with open(unternehmen_cache_file, "w", encoding="utf-8") as f:
        json.dump(unternehmen_geocode_cache, f, ensure_ascii=False, indent=2)

    # Jobangebote herausfilter, die wegen Berufsverbot nicht angezeigt werden dürfen
    berufsverbot = check_berufsverbot(buerger_id)
    if berufsverbot:
        berufsverbote = get_berufsverbote()
        offene_stellen = [
            stelle for stelle in offene_stellen
            if stelle.get("bezeichnung") not in berufsverbote
        ]

    jobangebote_liste = [stelle for stelle in offene_stellen if stelle.get("art", "") == "anstellung"]

    jobangebote_bereiche_filter_liste = sorted({
        bereich
        for stelle in jobangebote_liste
        for bereich in stelle.get("bereiche", [])
    })

    if filter_jobangebote_kennwortsuche:
        jobangebote_liste = [
            jobangebot for jobangebot in jobangebote_liste
            if filter_jobangebote_kennwortsuche.lower() in jobangebot.get("unternehmen_name", "").lower() or
               filter_jobangebote_kennwortsuche.lower() in jobangebot.get("bezeichnung", "").lower() or
               filter_jobangebote_kennwortsuche.lower() in jobangebot.get("voraussetzungen", "").lower()
        ]

    if filter_jobangebote_bereich != "all":
        jobangebote_liste = [
            jobangebot for jobangebot in jobangebote_liste
            if filter_jobangebote_bereich in [bereich.lower() for bereich in jobangebot.get("bereiche", [])]
        ]


    ausbildungen_liste = [stelle for stelle in offene_stellen if stelle.get("art", "") == "ausbildung"]

    ausbildungen_bereiche_filter_liste = sorted({
        bereich
        for stelle in ausbildungen_liste
        for bereich in stelle.get("bereiche", [])
    })
    
    if filter_ausbildungen_kennwortsuche:
        ausbildungen_liste = [
            ausbildung for ausbildung in ausbildungen_liste
            if filter_ausbildungen_kennwortsuche.lower() in ausbildung.get("unternehmen_name", "").lower() or
               filter_ausbildungen_kennwortsuche.lower() in ausbildung.get("bezeichnung", "").lower() or
               filter_ausbildungen_kennwortsuche.lower() in ausbildung.get("voraussetzungen", "").lower()
        ]

    if filter_ausbildungen_bereich != "all":
        ausbildungen_liste = [
            ausbildung for ausbildung in ausbildungen_liste
            if filter_ausbildungen_bereich in [bereich.lower() for bereich in ausbildung.get("bereiche", [])]
        ]


    studium_liste = [stelle for stelle in offene_stellen if stelle.get("art", "") in ("studium", "duales_studium")]
    
    studium_bereiche_filter_liste = sorted({
        bereich
        for stelle in studium_liste
        for bereich in stelle.get("bereiche", [])
    })

    if filter_studium_kennwortsuche:
        studium_liste = [
            studium for studium in studium_liste
            if filter_studium_kennwortsuche.lower() in studium.get("unternehmen_name", "").lower() or
               filter_studium_kennwortsuche.lower() in studium.get("bezeichnung", "").lower() or
               filter_studium_kennwortsuche.lower() in studium.get("voraussetzungen", "").lower()
        ]

    if filter_studium_bereich != "all":
        studium_liste = [
            studium for studium in studium_liste
            if filter_studium_bereich in [bereich.lower() for bereich in studium.get("bereiche", [])]
        ]

    if filter_studium_dual == 'ja':
        studium_liste = [studium for studium in studium_liste if studium.get("art", "") == "duales_studium"]
    elif filter_studium_dual == 'nein':
        studium_liste = [studium for studium in studium_liste if studium.get("art", "") == "studium"]

    geolocator = Nominatim(user_agent = "arbeitbildung_app")
    stammdaten = ermittle_buerger_stammdaten(buerger_id)

    try:
        buerger_location = geolocator.geocode(stammdaten['adresse'], timeout = 10)
        buerger_coords = [ buerger_location.longitude, buerger_location.latitude ]
    except Exception as e:
        buerger_coords = None 

    return render(request, 'arbeitbildung/buerger/jobboerse.html', {
        'role': 'buerger',
        'active_page': 'buerger_jobboerse',
        'username': request.session.get("buerger_name", buerger_id),
        'kind_alter': kind_alter,
        'aktuelle_beschaeftigung': aktuelle_beschaeftigung,
        'jobangebote_liste': jobangebote_liste,
        'ausbildungen_liste': ausbildungen_liste,
        'studium_liste': studium_liste,
        'jobangebote_bereiche_filter_liste': jobangebote_bereiche_filter_liste,
        'ausbildungen_bereiche_filter_liste': ausbildungen_bereiche_filter_liste,
        'studium_bereiche_filter_liste': studium_bereiche_filter_liste,
        'filter_jobangebote_kennwortsuche': filter_jobangebote_kennwortsuche,
        'filter_jobangebote_bereich': filter_jobangebote_bereich,
        'filter_ausbildungen_kennwortsuche': filter_ausbildungen_kennwortsuche,
        'filter_ausbildungen_bereich': filter_ausbildungen_bereich,
        'filter_studium_kennwortsuche': filter_studium_kennwortsuche,
        'filter_studium_bereich': filter_studium_bereich,
        'filter_studium_dual': filter_studium_dual,
        'buerger_coords': buerger_coords
    })

##############################
######## Bewerbungen #########
##############################

def buerger_bewerbungen(request):
  
    buerger_id = request.session.get('buerger_id')
    if not buerger_id:
        buerger_id = 'buerger0001'   #! Testbürger, später einfach entfernen
        request.session['buerger_id'] = buerger_id

    filter_kennwortsuche = ""
    filter_rueckmeldung = "all"

    if request.method == "POST":
        filter_kennwortsuche = request.POST.get("filter_kennwortsuche", "").strip()
        filter_rueckmeldung = request.POST.get("filter_rueckmeldung", "all").strip()
        action = request.POST.get("action", "")

        if action != "":
            unternehmen_id = request.POST.get("unternehmen_id", "")
            stelle_id = request.POST.get("stelle_id", "")

            buerger_dir = os.path.join(DATA_DIR, "buerger", f"{buerger_id}.json")
            with open(buerger_dir, "r", encoding = "utf-8") as f:
                buerger_daten = json.load(f)

            unternehmen_dir = os.path.join(DATA_DIR, "unternehmen", f"{unternehmen_id}.json")
            with open(unternehmen_dir, "r", encoding = "utf-8") as f:
                unternehmen_daten = json.load(f)

            for bewerbung in buerger_daten.get("bewerbungen", []):
                if bewerbung.get("arbeitgeber") == unternehmen_id and bewerbung.get("stelle") == stelle_id:
                    if action == "angebot_annehmen":
                        bewerbung["status"] = "eingestellt"
                    elif action == "angebot_ablehnen":
                        bewerbung["status"] = "abgelehntBürger"
                    elif action == "bewerbung_zurueckziehen":
                        bewerbung["status"] = "zurückgezogen"
                    break

            stelle_art = ""
            stelle_name = ""
            for stelle in unternehmen_daten.get("stellen", []):
                if stelle.get("id") == stelle_id:
                    if action == "angebot_annehmen":
                        stelle["besetzt"] = True
                        stelle["buerger"] = buerger_id
                    stelle_art = stelle.get("art", "")
                    stelle_name = stelle.get("bezeichnung", "")
                    stelle_dauer = stelle.get("dauer", 0)
                    break

            for bewerbung in unternehmen_daten.get("bewerbungen", []):
                if bewerbung.get("bewerber") == buerger_id and bewerbung.get("stelle") == stelle_id:
                    if action == "angebot_annehmen":
                        bewerbung["status"] = "eingestellt"
                    elif action == "angebot_ablehnen":
                        bewerbung["status"] = "abgelehntBürger"
                    elif action == "bewerbung_zurueckziehen":
                        bewerbung["status"] = "zurückgezogen"
                    break

            if action == "angebot_annehmen":
                lebenslauf = buerger_daten.get("lebenslauf", [])
                letzter_arbeitgeber = False
                letzte_bildungseinrichtung = False
                letzte_stelle = False

                if len(lebenslauf) > 0:
                    if lebenslauf[-1].get("ende", None) != None:
                        lebenslauf[-1]["ende"] = datetime.now().strftime("%Y-%m-%d")
                        if lebenslauf[-1].get("bildungseinrichtung", False) != False:
                            letzte_bildungseinrichtung = lebenslauf[-1]["bildungseinrichtung"]
                        elif lebenslauf[-1].get("arbeitgeber", False) != False and lebenslauf[-1].get("stelle", False) != False:
                            letzter_arbeitgeber = lebenslauf[-1]["arbeitgeber"]
                            letzte_stelle = lebenslauf[-1]["stelle"]

                jetzt = datetime.now()
                enddatum = False

                if stelle_dauer != 0:
                    enddatum = (jetzt + relativedelta(months=stelle_dauer)).strftime("%Y-%m-%d")

                lebenslauf.append({
                    "beginn": jetzt.strftime("%Y-%m-%d"),
                    "ende": enddatum,
                    "art": stelle_art,
                    "bildungseinrichtung": False,
                    "arbeitgeber": unternehmen_id,
                    "stelle": stelle_id,
                    "zeugnis": {}
                })

                buerger_daten["lebenslauf"] = lebenslauf

                if letzte_bildungseinrichtung:
                    letzte_bildungseinrichtung_dir = os.path.join(DATA_DIR, "bildungseinrichtungen", f"{letzte_bildungseinrichtung}.json")
                    with open(letzte_bildungseinrichtung_dir, "r", encoding = "utf-8") as f:
                        letzte_bildungseinrichtung_daten = json.load(f)
                    letzte_bildungseinrichtung_daten["schueler"] = [
                        schüler for schüler in letzte_bildungseinrichtung_daten["schueler"] if schüler["id"] != buerger_id
                    ]
                    postfach_letzte_bildungseinrichtung = letzte_bildungseinrichtung_daten.get("postfach", [])
                    postfach_letzte_bildungseinrichtung.insert(0, {
                        "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                        "beschreibung": "Hat die Bildungseinrichtung verlassen.",
                        "status": True
                    })
                    letzte_bildungseinrichtung_daten["postfach"] = postfach_letzte_bildungseinrichtung
                    with open(letzte_bildungseinrichtung_dir, "w", encoding = "utf-8") as f:
                        json.dump(letzte_bildungseinrichtung_daten, f, indent = 2, ensure_ascii = False)

                elif letzter_arbeitgeber:
                    letzter_arbeitgeber_dir = os.path.join(DATA_DIR, "unternehmen", f"{letzter_arbeitgeber}.json")
                    with open(letzter_arbeitgeber_dir, "r", encoding = "utf-8") as f:
                        letzter_arbeitgeber_daten = json.load(f)
                    letzte_stelle_name = ""
                    for letzter_arbeitgeber_stelle in letzter_arbeitgeber_daten["stellen"]:
                        if letzter_arbeitgeber_stelle["id"] == letzte_stelle and letzter_arbeitgeber_stelle["buerger"] == buerger_id:
                            letzter_arbeitgeber_stelle["besetzt"] = False
                            letzter_arbeitgeber_stelle["buerger"] = ""
                            letzte_stelle_name = letzter_arbeitgeber_stelle.get("bezeichnung", "")
                    postfach_letzter_arbeitgeber = letzter_arbeitgeber_daten.get("postfach", [])
                    postfach_letzter_arbeitgeber.insert(0, {
                        "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                        "beschreibung": f"Hat die Stelle {letzte_stelle_name} ({letzte_stelle}) gekündigt. Die Stelle ist nun wieder offen.",
                        "verlinkung": reverse('unternehmen/bewerber'), # Erstellt die entsprechende URL des Servers
                        "status": True
                    })
                    letzter_arbeitgeber_daten["postfach"] = postfach_letzter_arbeitgeber
                    with open(letzter_arbeitgeber_dir, "w", encoding = "utf-8") as f:
                        json.dump(letzter_arbeitgeber_daten, f, indent = 2, ensure_ascii = False)

            nachricht = ""
            verlinkung = ""
            if action == "angebot_annehmen":
                nachricht = f"Hat das Stellenangebot für {stelle_name} ({stelle_id}) angenommen."
                verlinkung = "unternehmen/mitarbeiter"
            elif action == "angebot_ablehnen":
                nachricht = f"Hat das Stellenangebot für {stelle_name} ({stelle_id}) abgelehnt."
                verlinkung = "unternehmen/bewerber"
            elif action == "bewerbung_zurueckziehen":
                nachricht = f"Hat seine Bewerbung für {stelle_name} ({stelle_id}) zurückgezogen."
                verlinkung = "unternehmen/bewerber"

            postfach_unternehmen = unternehmen_daten.get("postfach", [])
            postfach_unternehmen.insert(0, { # Setzt den Eintrag an die erste Stelle der Liste
                "sender": ermittle_buerger_stammdaten(buerger_id).get("name", "Unbekannt"),
                "beschreibung": nachricht,
                "verlinkung": reverse(verlinkung), # Erstellt die entsprechende URL des Servers
                "status": True
            })
            unternehmen_daten["postfach"] = postfach_unternehmen

            with open(buerger_dir, "w", encoding = "utf-8") as f:
                json.dump(buerger_daten, f, indent = 2, ensure_ascii = False)

            with open(unternehmen_dir, "w", encoding = "utf-8") as f:
                json.dump(unternehmen_daten, f, indent = 2, ensure_ascii = False)

            if action == "angebot_annehmen":
                messages.success(request, "Du hast das Stellenangebot erfolgreich angenommen!")
            elif action == "angebot_ablehnen":
                messages.info(request, "Du hast das Stellenangebot abgelehnt!")
            elif action == "bewerbung_zurueckziehen":
                messages.info(request, "Du hast deine Bewerbung zurückgezogen!")

    buerger_dir = os.path.join(DATA_DIR, "buerger", f"{buerger_id}.json")
    unternehmen_dir = os.path.join(DATA_DIR, "unternehmen")
    kind_alter = get_kind_alter()

    # Art Beschäftigung heraussuchen
    aktuelle_beschaeftigung = None
    with open(os.path.join(buerger_dir), "r", encoding = "utf-8") as f:
        buerger_daten = json.load(f)
        lebenslauf = buerger_daten.get("lebenslauf", [])
        if len(lebenslauf) > 0:
            if lebenslauf[-1].get("ende", False) is False and lebenslauf[-1].get("art", False) in ["tot", "rente", "haft"]:
                aktuelle_beschaeftigung = lebenslauf[-1]["art"]
    if aktuelle_beschaeftigung is None:
        alter = get_alter(buerger_id)
        if alter is not None and alter < kind_alter:
            aktuelle_beschaeftigung = "kind"
        elif check_berufsverbot(buerger_id):
            aktuelle_beschaeftigung = "berufsverbot"


    unternehmen_cache_file = os.path.join(unternehmen_dir, "geocode_cache.json")
    unternehmen_geocode_cache = {}
    geolocator = Nominatim(user_agent = "arbeitbildung_app")

    if os.path.exists(unternehmen_cache_file):
        with open(unternehmen_cache_file, "r", encoding="utf-8") as f:
            unternehmen_geocode_cache = json.load(f)

    alle_bewerbungen = []
    with open(buerger_dir, "r", encoding = "utf-8") as f:
        buerger_daten = json.load(f)
        for bewerbung_daten in buerger_daten.get("bewerbungen", []):
            unternehmen_id = bewerbung_daten.get("arbeitgeber")
            stelle_id = bewerbung_daten.get("stelle")

            # Bewerbung unvollständig -> überspringen
            if not unternehmen_id or not stelle_id:
                print(f"[BEWERBUNGEN] Übersprungen (fehlende IDs): {bewerbung_daten}")
                continue

            unternehmen_path = os.path.join(unternehmen_dir, f"{unternehmen_id}.json")

            # Unternehmen-Datei existiert nicht -> überspringen 
            if not os.path.exists(unternehmen_path):
                print(f"[BEWERBUNGEN] Unternehmen-Datei fehlt: {unternehmen_path}")
                continue

            with open(unternehmen_path, "r", encoding="utf-8") as unternehmen_f:
                unternehmen_daten = json.load(unternehmen_f)

            stelle_daten = {}
            for stelle in unternehmen_daten.get("stellen", []):
                if stelle.get("id") == stelle_id:
                    stelle_daten = stelle
                    break
            bewerbungsdatum = bewerbung_daten.get("bewerbungsdatum")
            bewerbungsdatum = datetime.strptime(bewerbungsdatum, "%Y-%m-%d").strftime("%Y-%m-%d")
            rückmeldedatum = bewerbung_daten.get("rückmeldedatum")
            if rückmeldedatum is not False:
                rückmeldedatum = datetime.strptime(rückmeldedatum, "%Y-%m-%d").strftime("%Y-%m-%d")
            adresse = unternehmen_daten.get("adresse", "")
            if adresse not in unternehmen_geocode_cache:
                try:
                    location = geolocator.geocode(adresse, timeout=10)
                except Exception as e:
                    location = None
                if location:
                    coords = {"lat": location.latitude, "lng": location.longitude}
                    unternehmen_geocode_cache[adresse] = coords
            alle_bewerbungen.append({
                "unternehmen_id": unternehmen_id,
                "stelle_id": stelle_id,
                "status": bewerbung_daten.get("status"),
                "bewerbungsdatum": bewerbungsdatum,
                "rueckmeldedatum": rückmeldedatum,
                "unternehmen_name": unternehmen_daten.get("name"),
                "unternehmen_adresse": adresse,
                "unternehmen_coords": unternehmen_geocode_cache.get(adresse),
                "bezeichnung": stelle_daten.get("bezeichnung"),
                "beschreibung": stelle_daten.get("beschreibung"),
                "bereiche": stelle_daten.get("bereiche"),
                "voraussetzungen": stelle_daten.get("voraussetzungen"),
                "gehalt": stelle_daten.get("gehalt"),
                "gehalt_str": f"{stelle_daten.get("gehalt"):,}".replace(",", "."),
                "art": stelle_daten.get("art"),
                "art_str": stelle_daten.get("art").replace("_", " ").title(),
                "dauer": stelle_daten.get("dauer")
            })

    with open(unternehmen_cache_file, "w", encoding="utf-8") as f:
        json.dump(unternehmen_geocode_cache, f, ensure_ascii=False, indent=2)

    vergangene_bewerbungen = [bewerbung for bewerbung in alle_bewerbungen if bewerbung.get("status") in ("abgelehntUnternehmen", "abgelehntBürger", "zurückgezogen", "eingestellt")]
    vergangene_bewerbungen.reverse()

    aktuelle_bewerbungen = [bewerbung for bewerbung in alle_bewerbungen if bewerbung.get("status") in ("offen", "angebot")]

    if filter_kennwortsuche:
        aktuelle_bewerbungen = [
            bewerbung for bewerbung in aktuelle_bewerbungen
            if filter_kennwortsuche.lower() in bewerbung.get("unternehmen_name", "").lower() or
               filter_kennwortsuche.lower() in bewerbung.get("bezeichnung", "").lower()
        ]

    if filter_rueckmeldung == 'ja':
        aktuelle_bewerbungen = [bewerbung for bewerbung in aktuelle_bewerbungen if bewerbung.get("status", "") == "angebot"]
    elif filter_rueckmeldung == 'nein':
        aktuelle_bewerbungen = [bewerbung for bewerbung in aktuelle_bewerbungen if bewerbung.get("status", "") == "offen"] 

    return render(request, 'arbeitbildung/buerger/bewerbungen.html', {
        'role': 'buerger',
        'active_page': 'buerger_bewerbungen',
        'username': request.session.get("buerger_name", buerger_id),
        'kind_alter': kind_alter,
        'aktuelle_beschaeftigung': aktuelle_beschaeftigung,
        'vergangene_bewerbungen_liste': vergangene_bewerbungen,
        'aktuelle_bewerbungen_liste': aktuelle_bewerbungen,
        'filter_kennwortsuche': filter_kennwortsuche,
        'filter_rueckmeldung': filter_rueckmeldung
    })

##############################
########## Postfach ##########
##############################

def buerger_postfach(request):

   # Buerger-ID aus Session oder statisch
     # Bürger-ID aus der Session holen, sonst Standard buerger0001 setzen
    buerger_id = request.session.get('buerger_id')
    if not buerger_id:
        buerger_id = 'buerger0001'   # Testbürger, später einfach entfernen
        request.session['buerger_id'] = buerger_id
    json_pfad = os.path.join(DATA_DIR,'buerger', f"{buerger_id}.json")

      # JSON der Bürger laden
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

    return render(request, 'arbeitbildung/buerger/postfach.html', {
        'role': 'buerger',
        'active_page': 'buerger_postfach',
        'username': request.session.get("buerger_name", buerger_id),
        'postfach': daten.get('postfach', [])
     })