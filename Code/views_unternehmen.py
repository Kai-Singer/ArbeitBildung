# Leonie Waimer

from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse
from django.contrib import messages
from datetime import date, datetime, timedelta
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
import json
import os
import requests

# ===============================
# ====== Datei-Pfade ============
# ===============================
#DATA_DIR = '/var/www/django-project/arbeitbildung/data'
arbeitgeberData = '/var/www/django-project/arbeitbildung/data/unternehmen/'
unternehmenRegister = '/var/www/django-project/arbeitbildung/data/unternehmen/registerUnternehmen.json'
adminData = '/var/www/django-project/arbeitbildung/data/admin/admin.json'
buergerDaten = '/var/www/django-project/arbeitbildung/data/buerger/'
API_Meldewesen_URL = "http://[2001:7c0:2320:2:f816:3eff:fef8:f5b9]:8000/einwohnermeldeamt/api/abfrage/beruf_ausbildung"

# Kai Singer

#################################################
######### Gehalt Überweisung - Crontab ##########
#################################################

def cron_run_gehalt_ueberweisung():
  # konto_liste = requests.get("http://[2001:7c0:2320:2:f816:3eff:fe82:34b2]:8000/bank/zeigeKonten", timeout = 10)
  # if not konto_liste:
  #   print("[CRON] Die Konto Liste konnte nicht gefunden werden.")
  #   return
  # konten = konto_liste.get("konten", [])
  for dateiname in os.listdir(arbeitgeberData):
    dateipfad = os.path.join(arbeitgeberData, dateiname)
    if not dateiname.startswith("u"):
      continue
    if os.path.isfile(dateipfad):
      with open(dateipfad, "r", encoding="utf-8") as f:
        unternehmen_daten = json.loads(f.read())
      unternehmen_id = unternehmen_daten.get("id")
      # unternehmen_konto = ""
      # for konto in konten:
      #   if konto.get("id", "") == unternehmen_id:
      #     unternehmen_konto = konto.get("Kontonummer", "")
      #     break
      # if unternehmen_konto == "":
      #   print(f"[CRON] Das Konto von Unternehmen {unternehmen_id} konnte nicht gefunden werden.")
      #   continue
      if unternehmen_daten.get("aktiv", False) == False:
        print(f"[CRON] Das Unternehmen {unternehmen_id} ist nicht aktiv.")
        continue
      stellen = unternehmen_daten.get("stellen", [])
      for stelle in stellen:
        if stelle.get("besetzt", False) == True:
          buerger = stelle.get("buerger", None)
          gehalt = stelle.get("gehalt", None)
          # buerger_konto = ""
          # for konto in konten:
          #   if konto.get("id", "") == buerger:
          #     buerger_konto = konto.get("Kontonummer", "")
          #     break
          # if buerger_konto == "":
          #   print(f"[CRON] Das Konto von Bürger {buerger} konnte nicht gefunden werden.")
          #   continue
          # response = requests.get(f"http://[2001:7c0:2320:2:f816:3eff:fe82:34b2]:8000/bank/zahlungVerarbeiten?empf={ buerger_konto }&sender={ unternehmen_konto }&betrag={ gehalt }&VWZ=Gehalt", timeout = 10)
          postData = json.dumps({
            "sender": unternehmen_id,
            "empf": buerger,
            "betrag": gehalt,
            "VWZ": "Gehalt"
          })
          response = requests.post("http://[2001:7c0:2320:2:f816:3eff:fee6:5d97]:8000/bank/gehalt", data = postData, timeout = 10)
          if response.status_code != 200:
            print(f"[CRON] Das Gehalt von Unternehmen {unternehmen_id} an Bürger {buerger} konnte nicht überwiesen werden. - {response.text}")

# Leonie Waimer

##############################
########## Anmeldung #########
##############################

def unternehmen_anmeldung(request):

    with open(unternehmenRegister, "r", encoding="utf-8") as file:
        unternehmenListe = json.load(file)

    if request.method == "POST":
        unternehmenId = request.POST.get("unternehmenId")
        passwort = request.POST.get("passwort")

        for unternehmen in unternehmenListe:
            if str(unternehmen["id"]) == str(unternehmenId) and unternehmen["passwort"] == passwort:
                benutzername = unternehmen["name"]
                request.session["unternehmen_id"] = unternehmen["id"]
                request.session["unternehmen_name"] = unternehmen["name"]

                messages.success(request, f"Erfolgreich angemeldet als {benutzername}.")
                return redirect("unternehmen/dashboard")

        messages.error(request, "ID oder Passwort falsch.")

    return render(request, "arbeitbildung/unternehmen/anmeldung.html")

##############################
##### Registreierung #########
##############################

def unternehmen_registrierung(request):

    if request.method == 'POST':
        name = request.POST.get('benutzername')
        adresse = request.POST.get('adresse')
        passwort = request.POST.get('passwort')

        vorhandene_ids = []
        for datei in os.listdir(arbeitgeberData):
            if datei.startswith("u") and datei.endswith(".json"):
                with open(os.path.join(arbeitgeberData, datei), encoding="utf-8") as file:
                    daten = json.load(file)
                    if isinstance(daten, list) and daten:
                       daten = daten[0]
                    vorhandene_ids.append(int(daten["id"][1:]))
        neue_id = f"u{max(vorhandene_ids, default=0) + 1:04d}"

        neue_daten = {
            "id": neue_id,
            "aktiv": True,
            "name": name,
            "adresse": adresse,
            "stellen": [],
            "bewerbungen": [],
            "postfach": []
        }

        with open(os.path.join(arbeitgeberData, f"{neue_id}.json"), "w", encoding="utf-8") as file:
            json.dump(neue_daten, file, indent=4, ensure_ascii=False)

        try:
            with open(unternehmenRegister, "r", encoding="utf-8") as file:
                unternehmenListe = json.load(file)
        except FileNotFoundError:
            unternehmenListe = []

        unternehmenListe.append({
            "id": neue_id,
            "name": name,
            "passwort": passwort
        })

        with open(unternehmenRegister, "w", encoding="utf-8") as file:
            json.dump(unternehmenListe, file, indent=4)

        api_url = "http://[2001:7c0:2320:2:f816:3eff:fe82:34b2]:8000/bank/MELDUNG"
        payload= {
           "buerger_id": neue_id,
           "vorname": name,
           "nachname": ""
        }
        requests.post(api_url, data=payload)

        infoText = f"Neue Registrierung:\n\nUnternehmens-ID: {neue_id}\nBitte merken Sie sich diese ID für die Anmeldung."

        return render(request, 'arbeitbildung/unternehmen/registrierung.html', {
          "infoText": infoText,
          "neueID": neue_id
        })

    return render(request, 'arbeitbildung/unternehmen/registrierung.html', {
          "infoText": None
        })

##############################
######### Dashboard ##########
##############################

def unternehmen_dashboard(request):

  unternehmen_id = request.session.get("unternehmen_id")
  username = request.session.get("unternehmen_name")
  if not unternehmen_id:
     return redirect("unternehmen/anmeldung")
  json_pfad = os.path.join(arbeitgeberData, f"{unternehmen_id}.json")

  with open(json_pfad, "r", encoding="utf-8") as file:
    arbeitgeberregister = json.load(file)

  #----------------------------------------------------------------------------
  # Offene Stellen zählen
  #----------------------------------------------------------------------------
  offene_stellen = []
  for stelle in arbeitgeberregister.get("stellen", []):
    if stelle["aktiv"] and not stelle.get("besetzt", False):
      offene_stellen.append(stelle)
  anzahl_offene_stellen = len(offene_stellen)

  #----------------------------------------------------------------------------
  # Mitarbeiter zählen
  #----------------------------------------------------------------------------
  mitarbeiter = []
  for stelle in arbeitgeberregister.get("stellen", []):
    if stelle.get("besetzt", False):
      mitarbeiter.append(stelle)
  anzahl_mitarbeiter = len(mitarbeiter)

  #----------------------------------------------------------------------------
  # ungelesene Nachrichten zählen
  #----------------------------------------------------------------------------
  ungelesene_nachrichten = []
  for nachricht in arbeitgeberregister.get("postfach", []):
    if nachricht.get("status", False):
      ungelesene_nachrichten.append(nachricht)
  anzahl_ungelesene_nachrichten = len(ungelesene_nachrichten)

  #----------------------------------------------------------------------------
  # Nachricht an Postfach des Admin senden
  #----------------------------------------------------------------------------
  if request.method == 'POST':
     nachricht = request.POST.get('nachricht', '').strip()
     if nachricht:
        with open(adminData, "r", encoding="utf-8") as file:
          adminDaten = json.load(file)
        adminDaten["postfach"].insert(0,{ 
           "sender": unternehmen_id,
           "beschreibung": nachricht,
           "status": True
        })
        with open(adminData, "w", encoding="utf-8") as file:
          json.dump(adminDaten, file, indent=2, ensure_ascii=False)
        messages.success(request, "Deine Nachricht wurde erfolgreich gesendet!")
        return redirect('unternehmen/dashboard')

  return render(request, 'arbeitbildung/unternehmen/dashboard.html', {
    'role': 'unternehmen',
    'active_page': 'unternehmen_dashboard',
    'username': username,
    'offene_stellen': anzahl_offene_stellen,
    'mitarbeiter': anzahl_mitarbeiter,
    'ungelesene_nachrichten': anzahl_ungelesene_nachrichten,
    'unternehmen_id': unternehmen_id
  })

##############################
########## Bewerber ##########
##############################

def unternehmen_bewerber(request):
  
  unternehmen_id = request.session.get("unternehmen_id")
  username = request.session.get("unternehmen_name")
  if not unternehmen_id:
    return redirect("unternehmen/anmeldung")
  json_pfad = os.path.join(arbeitgeberData, f"{unternehmen_id}.json")

  with open(json_pfad, "r", encoding="utf-8") as file:
    arbeitgeberregister = json.load(file)

  #----------------------------------------------------------------------------
  # Stelle deaktivieren / aktivieren 
  #----------------------------------------------------------------------------
  if request.method == 'POST':
    stelleID = request.POST.get('stelleID')
    aktion = request.POST.get('aktion')
    if stelleID and aktion:
      for stelle in arbeitgeberregister['stellen']:
        if stelle['id'] == stelleID:
          if aktion == 'deaktivieren':
            stelle['aktiv'] = False
            messages.error(request, "Die Stelle wurde deaktiviert.")
          elif aktion == 'aktivieren':
            stelle['aktiv'] = True
            messages.success(request, "Die Stelle wurde aktiviert.")
          with open(json_pfad, "w", encoding="utf-8") as file:
            json.dump(arbeitgeberregister, file, indent = 2, ensure_ascii=False)
          return redirect("unternehmen/bewerber")
        
  #----------------------------------------------------------------------------
  # Bewerbungen verwalten (annehmen oder ablehnen)
  #----------------------------------------------------------------------------
  if request.method == "POST":
    bewerberID = request.POST.get("bewerberID")
    stellenID = request.POST.get("bewerbungsStelleID")
    aktionBewerbung = request.POST.get("aktionBewerbung")
    stellenbezeichnung = ""
    for stelle in arbeitgeberregister['stellen']:
      if stelle['id'] == stellenID:
        stellenbezeichnung = stelle['bezeichnung']
        break
    if aktionBewerbung in ["bewerbungAnnehmen", "bewerbungAblehnen"]:
      if aktionBewerbung == "bewerbungAnnehmen":
        neuerStatus = "angebot"
        nachrichtBuerger = f"Herzlichen Glückwunsch! Ihre Bewerbung wurde beim Unternehmen {username} für die Stelle {stellenbezeichnung} angenommen. "
        messages.success(request, "Die Bewerbung wurde angenommen.")
      else:
        neuerStatus = "abgelehntUnternehmen"
        nachrichtBuerger = f"Leider wurde Ihre Bewerbung beim Unternehmen {username} für die Stelle {stellenbezeichnung} abgelehnt."
        messages.error(request, "Die Bewerbung wurde abgelehnt.")
      geandert = False
      for bewerbung in arbeitgeberregister["bewerbungen"]:
        if str(bewerbung["bewerber"]) == str(bewerberID) and str(bewerbung["stelle"]) == str(stellenID):
          bewerbung["status"] = neuerStatus
          bewerbung["rückmeldedatum"] = date.today().isoformat()
          geandert = True
          break
      if geandert:
        with open(json_pfad, "w", encoding="utf-8") as file:
          json.dump(arbeitgeberregister, file, indent = 2, ensure_ascii=False)

        buergerJSONPfad = os.path.join(buergerDaten, f"{bewerberID}.json")
        with open(buergerJSONPfad, "r", encoding="utf-8") as file:
          buergerDatenRegister = json.load(file)
        geandertBuerger = False
        for bewerbung in buergerDatenRegister["bewerbungen"]:
          if bewerbung["arbeitgeber"] == unternehmen_id and bewerbung["stelle"] == stellenID:
            bewerbung["status"] = "angebot" if aktionBewerbung == "bewerbungAnnehmen" else "abgelehntUnternehmen"
            bewerbung["rückmeldedatum"] = date.today().isoformat()
            geandertBuerger = True
            break
        buergerDatenRegister["postfach"].insert(0, {
           "sender": username,
           "beschreibung": nachrichtBuerger,
           "verlinkung": "http://[2001:7c0:2320:2:f816:3eff:feb6:6731]:8000/buerger/bewerbungen",
           "status": True
        })
        if geandertBuerger:
          with open(buergerJSONPfad, "w", encoding="utf-8") as file:
            json.dump(buergerDatenRegister, file, indent = 2, ensure_ascii=False)
      return redirect("unternehmen/bewerber")
  
  #----------------------------------------------------------------------------
  # offene Stelle bearbeiten
  #----------------------------------------------------------------------------
  if request.POST.get("aktionStelleBearbeiten") == "stelleBearbeiten":
    stellenID = request.POST.get("offeneStellenID")
    bezeichnung = request.POST.get("bezeichnung")
    bereiche = request.POST.get("bereiche")
    voraussetzungen = request.POST.get("voraussetzungen")
    gehalt = request.POST.get("gehalt")
    anstellungsart = request.POST.get("anstellungsart")
    beschreibung = request.POST.get("beschreibung")
    dauer = request.POST.get("dauer")
    for stelle in arbeitgeberregister['stellen']:
      if str(stelle["id"]) == str(stellenID): 
        stelle['bezeichnung'] = bezeichnung
        stelle['bereiche'] = (bereiche or "").split(",")
        stelle['voraussetzungen'] = voraussetzungen
        stelle['gehalt'] = int(gehalt) if gehalt else 0
        stelle['art'] = anstellungsart
        stelle['beschreibung'] = beschreibung
        if stelle["art"] in ["ausbildung", "studium", "duales_studium"]:
          stelle["dauer"] = int(dauer) if dauer else 0
        else:
          stelle["dauer"] = 0
        messages.success(request, "Die Stelle wurde erfolgreich bearbeitet.")
        break
    with open(json_pfad, "w", encoding="utf-8") as file:
      json.dump(arbeitgeberregister, file, indent = 2, ensure_ascii=False)
    return redirect("unternehmen/bewerber")
  
  #----------------------------------------------------------------------------
  # Neue Stelle erstellen
  #----------------------------------------------------------------------------
  if request.method == "POST" and request.POST.get("aktionNeueStelle") == "neueStelleErstellen":
    bezeichnung = request.POST.get("bezeichnung")
    bereiche = request.POST.get("bereiche", "")
    bereicheListe = []
    if bereiche:
      for bereich in bereiche.split(","):
        bereicheListe.append(bereich.strip())
    voraussetzungen = request.POST.get("voraussetzungen", "")
    gehalt = request.POST.get("gehalt")
    anstellungsart = request.POST.get("anstellungsart")
    beschreibung = request.POST.get("beschreibung", "")
    dauer = request.POST.get("dauer")
    höchsteNummerBisher = 0
    for stelle in arbeitgeberregister["stellen"]:
      idStelle = stelle.get("id", "")
      if idStelle.startswith("s"):
        nummer = int(idStelle[1:])
        höchsteNummerBisher = max(höchsteNummerBisher, nummer)
    neueID = f"s{höchsteNummerBisher + 1:04d}"
    neueStelle = {
      "id": str(neueID),
      "aktiv": True,
      "bezeichnung": bezeichnung,
      "beschreibung": beschreibung,
      "bereiche": bereicheListe,
      "voraussetzungen": voraussetzungen,
      "gehalt": int(gehalt) if gehalt else 0,
      "buerger": "",
      "besetzt": False,
      "art": anstellungsart,
      "dauer": int(dauer) if dauer and anstellungsart in ["ausbildung", "studium", "duales_studium"] else 0      
    }
    arbeitgeberregister["stellen"].append(neueStelle)
    with open(json_pfad, "w", encoding="utf-8") as file:
      json.dump(arbeitgeberregister, file, indent=2, ensure_ascii=False)
    messages.success(request, "Die neue Stelle wurde erfolgreich erstellt.")
    return redirect ("unternehmen/bewerber")
  
  #----------------------------------------------------------------------------
  # Offene Stellen anzeigen
  #----------------------------------------------------------------------------
  offeneStellen = []
  offeneStellenBereicheSet = set()
  offeneStellenStatusSet = set()
  for stelle in arbeitgeberregister['stellen']:
    if not stelle.get("besetzt", False):
      anzahlBewerbungen = 0
      for bewerbung in arbeitgeberregister['bewerbungen']:
        if bewerbung['stelle'] == stelle['id'] and bewerbung['status'] in ['offen', 'angebot', 'angebotFinal']:
          anzahlBewerbungen += 1
      stelle['anzahlBewerbungen'] = anzahlBewerbungen
      offeneStellen.append(stelle)

      for bereich in stelle.get("bereiche"):
        offeneStellenBereicheSet.add(bereich.strip())
      offeneStellenStatusSet.add("aktiv" if stelle.get("aktiv", False) else "deaktiviert")
  offeneStellen_bereiche_filter_liste = sorted(list(offeneStellenBereicheSet))
  offeneStellen_status_filter_liste = sorted(list(offeneStellenStatusSet))


  #----------------------------------------------------------------------------
  # Kennwortsuche und Bereichs-Filter für offene Stellen
  #----------------------------------------------------------------------------
  filter_offeneStellen_kennwortsuche = ""
  filter_offeneStellen_bereich = "all"
  filter_offeneStellen_status = "all"
  if request.method == "POST":
    filter_offeneStellen_kennwortsuche = request.POST.get("filter_offeneStellen_kennwortsuche", "").strip()
    filter_offeneStellen_bereich = request.POST.get("filter_offeneStellen_bereich", "all").strip().lower()
    filter_offeneStellen_status = request.POST.get("filter_offeneStellen_status", "all").strip().lower()
  gefilterteOffeneStellen = offeneStellen

  if filter_offeneStellen_kennwortsuche:
    suchbegriff = filter_offeneStellen_kennwortsuche.lower()
    neueListe = []
    for stelle in gefilterteOffeneStellen:
      bezeichnung = stelle.get("bezeichnung").lower()
      if suchbegriff in bezeichnung:
          neueListe.append(stelle)
    gefilterteOffeneStellen = neueListe

  if filter_offeneStellen_bereich != "all":
    bereichFilter = filter_offeneStellen_bereich.lower()
    neueListe = []
    for stelle in gefilterteOffeneStellen:
      bereicheListe = [b.strip().lower() for b in stelle.get("bereiche", [])]
      for bereich in bereicheListe:
        if bereich == bereichFilter:
            neueListe.append(stelle)
            break
    gefilterteOffeneStellen = neueListe
  
  if filter_offeneStellen_status != "all":
    neueListe = []
    for stelle in gefilterteOffeneStellen:
        aktiv = stelle.get("aktiv")
        if filter_offeneStellen_status == "aktiv" and aktiv or filter_offeneStellen_status == "deaktiviert" and not aktiv:
            neueListe.append(stelle)
    gefilterteOffeneStellen = neueListe

  #----------------------------------------------------------------------------
  # aktuelle Bewerbungen anzeigen
  #----------------------------------------------------------------------------
  aktuelleBewerber = []
  vergangeneBewerber = []
  for bewerbung in arbeitgeberregister['bewerbungen']:
    stellenbezeichnung = "unbekannt"
    for stelle in arbeitgeberregister['stellen']:
      if stelle['id'] == bewerbung['stelle']:
        stellenbezeichnung = stelle['bezeichnung']
        break
    # aktuelle Bewerbernamen aus API holen ------------------------------------------------------------
    bewerberID = bewerbung.get("bewerber")
    name = bewerberID
    response = requests.get(f"{API_Meldewesen_URL}/{bewerberID}", timeout = 5)
    buergerStammdaten = response.json()
    vorname = buergerStammdaten.get("vorname", "").strip()
    if buergerStammdaten.get("nachname_neu", ""):
      nachname = buergerStammdaten.get("nachname_neu", "").strip()
    else:
      nachname = buergerStammdaten.get("nachname_geburt", "").strip()
    vollerName = f"{vorname} {nachname}".strip()
    if vollerName:
      name = vollerName
    volleAdresse = "Unbekannt"
    if buergerStammdaten.get("wohnsitz"):
      adresse = buergerStammdaten.get("wohnsitz")
      strasse = adresse.get("straße_hausnummer","").strip()
      plz_ort = adresse.get("plz_ort","").strip()
      volleAdresse = f"{strasse}, {plz_ort}"
    geburtsdatum = buergerStammdaten.get("geburtsdatum", "")
    geburtsdatumFormatiert = ""
    if geburtsdatum:
      try:
        geburtsdatumFormatiert = datetime.strptime(geburtsdatum, "%Y-%m-%d").strftime("%Y-%m-%d")
      except ValueError:
        try:
          geburtsdatumFormatiert = datetime.strptime(geburtsdatum, "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
          geburtsdatumFormatiert = geburtsdatum

    # aktuellen Lebenslauf aus Bürger JSON holen ------------------------------------------------------------
    buergerJSONPfad = os.path.join(buergerDaten, f"{bewerberID}.json") 
    try:
      with open(buergerJSONPfad, "r", encoding="utf-8") as file: 
        buergerDatenRegister = json.load(file)
    except FileNotFoundError:
      buergerDatenRegister = {}
    lebenslauf = []
    for eintrag in buergerDatenRegister.get("lebenslauf", []):
      arbeitgeberName = ""
      stellenBezeichnung = ""
      bildungseinrichtungsName = ""
      abschlussBezeichnung = ""
      arbeitgeber_ID = eintrag.get("arbeitgeber", "")
      stellen_ID = eintrag.get("stelle", "")
      bildungseinrichtungs_ID = eintrag.get("bildungseinrichtung", "")
      if arbeitgeber_ID:
        with open(os.path.join(arbeitgeberData, f"{arbeitgeber_ID}.json"), "r", encoding="utf-8") as file:
          arbeitgeberDaten = json.load(file)
          arbeitgeberName = arbeitgeberDaten.get("name", "")
          for stelle in arbeitgeberDaten.get("stellen", []):
            if stelle.get("id", "") == stellen_ID:
              stellenBezeichnung = stelle.get("bezeichnung", "")
              break
      elif bildungseinrichtungs_ID:
        pfad_bildungseinrichtung = "/var/www/django-project/arbeitbildung/data/bildungseinrichtungen/"
        with open(os.path.join(pfad_bildungseinrichtung, f"{bildungseinrichtungs_ID}.json"), "r", encoding="utf-8") as file:
          bildungseinrichtungsDaten = json.load(file)
          bildungseinrichtungsName = bildungseinrichtungsDaten.get("name", "")
          abschlussBezeichnung = bildungseinrichtungsDaten.get("schulart", "")
      station = {
        "arbeitgeber": arbeitgeberName,
        "stelle": stellenBezeichnung,
        "bildungseinrichtung": bildungseinrichtungsName,
        "abschluss": abschlussBezeichnung,
        "beginn": eintrag.get("beginn", ""),
        "ende": eintrag.get("ende", ""),
        "zeugnis": {
          "beschreibung": eintrag.get("zeugnis", {}).get("beschreibung", ""),
          "note": eintrag.get("zeugnis", {}).get("abschlussnote", "")
        }
      }
      lebenslauf.insert(0, station)

    bewerbung['stellenbezeichnung'] = stellenbezeichnung    
    bewerbung['bewerberName'] = name  
    bewerbung['bewerberAdresse'] = volleAdresse
    bewerbung['bewerberGeburtsdatum'] = geburtsdatumFormatiert
    bewerbung['lebenslauf'] = lebenslauf
    if bewerbung['status'] in ['offen', 'angebot', 'angebotFinal']:
      aktuelleBewerber.append(bewerbung)
    else:
      vergangeneBewerber.append(bewerbung)

  #----------------------------------------------------------------------------
  # Kennwortsuche für aktuelle Bewerber
  #----------------------------------------------------------------------------
  filter_bewerber_kennwortsuche = ""
  if request.method == "POST":
    filter_bewerber_kennwortsuche = request.POST.get("filter_bewerber_kennwortsuche", "").strip()
  gefilterteBewerber = aktuelleBewerber
  if filter_bewerber_kennwortsuche:
    suchbegriff = filter_bewerber_kennwortsuche.lower()
    gefilterteBewerber = []
    for bewerberEintrag in aktuelleBewerber:
      name = bewerberEintrag.get("bewerberName").lower()
      bezeichnung = bewerberEintrag.get("stellenbezeichnung").lower()
      felder = [name, bezeichnung]
      for feld in felder:
        if suchbegriff in feld:
          gefilterteBewerber.append(bewerberEintrag)
          break

  return render(request, 'arbeitbildung/unternehmen/bewerber.html', {
    'role': 'unternehmen',
    'active_page': 'unternehmen_bewerber',
    'username': username,
    'offeneStellen': gefilterteOffeneStellen,
    'aktuelleBewerber': gefilterteBewerber,
    'vergangeneBewerber': vergangeneBewerber,
    'unternehmen_id': unternehmen_id,
    'filter_offeneStellen_kennwortsuche': filter_offeneStellen_kennwortsuche,
    'filter_bewerber_kennwortsuche': filter_bewerber_kennwortsuche,
    'filter_offeneStellen_bereich': filter_offeneStellen_bereich,
    'filter_offeneStellen_status': filter_offeneStellen_status,
    'offeneStellen_bereiche_filter_liste': offeneStellen_bereiche_filter_liste,
    'offeneStellen_status_filter_liste': offeneStellen_status_filter_liste
  })

##############################
######## Mitarbeiter #########
##############################

def unternehmen_mitarbeiter(request):

  unternehmen_id = request.session.get("unternehmen_id")
  username = request.session.get("unternehmen_name")
  if not unternehmen_id:
    return redirect("unternehmen/anmeldung")
  json_pfad = os.path.join(arbeitgeberData, f"{unternehmen_id}.json")

  with open(json_pfad, "r", encoding="utf-8") as file:
    arbeitgeberregister = json.load(file)

  #----------------------------------------------------------------------------
  # Mitarbeiter entlassen
  #----------------------------------------------------------------------------
  if request.method == "POST" and request.POST.get("aktion") == "entlassen":
    stellenID = request.POST.get("stellenID")
    buergerID = None
    for stelle in arbeitgeberregister.get("stellen"):
        if stelle.get("id") == stellenID:
           buergerID = stelle.get("buerger")
           stellenbezeichnung = stelle.get("bezeichnung", "")
           stelle["besetzt"] = False
           stelle["buerger"] = ""
           messages.success(request, "Der Mitarbeiter wurde entlassen.")
           break
    with open(json_pfad, "w", encoding="utf-8") as file:
      json.dump(arbeitgeberregister, file, indent=2, ensure_ascii=False)
    if buergerID:
      buergerPfad = os.path.join(buergerDaten, f"{buergerID}.json")
      with open(buergerPfad, "r", encoding="utf-8") as file:
        buergerDatenRegister = json.load(file)
      for eintrag in buergerDatenRegister.get("lebenslauf", []):
        arbeitgeber = str(eintrag.get("arbeitgeber")).strip()
        stelle = str(eintrag.get("stelle")).strip()
        if arbeitgeber == str(unternehmen_id) and stelle == str(stellenID):
          eintrag["ende"] = date.today().isoformat()
          break
      buergerDatenRegister["postfach"].insert(0, {
        "sender": username,
        "beschreibung": f"Sie wurden von dem Unternehmen {username} für die Stelle {stellenbezeichnung} entlassen.",
        "status": True
      })
      with open(buergerPfad, "w", encoding="utf-8") as file:
        json.dump(buergerDatenRegister, file, indent=2, ensure_ascii=False)

  #----------------------------------------------------------------------------
  # Stelle bearbeiten (Gehalt ändern)
  #----------------------------------------------------------------------------
  if request.method == "POST" and request.POST.get("aktion") == "stelle_bearbeiten":
    stellenID = request.POST.get("stellenID")
    neuesGehalt = request.POST.get("gehalt")
    for stelle in arbeitgeberregister.get("stellen"):
        if stelle.get("id") == stellenID:
           stelle["gehalt"] = int(neuesGehalt)
           messages.success(request, "Das Gehalt wurde erfolgreich aktualisiert.")
    with open(json_pfad, "w", encoding="utf-8") as file:
      json.dump(arbeitgeberregister, file, indent=2, ensure_ascii=False)

  #----------------------------------------------------------------------------
  # Zeugnis bearbeiten
  #----------------------------------------------------------------------------
  if request.method == "POST" and request.POST.get("aktion") == "zeugnis_bearbeiten":
    stellenID = request.POST.get("stellenID")
    buergerID = request.POST.get("buergerID")
    neueBeschreibung = request.POST.get("beschreibung", "")
    neueNote = request.POST.get("abschlussnote", "")
    buergerPfad = os.path.join(buergerDaten, f"{buergerID}.json")
    with open(buergerPfad, "r", encoding="utf-8") as file:
      buerger = json.load(file)
    for eintrag in buerger.get("lebenslauf"):
      if eintrag.get("stelle") == stellenID:
        passendeStelle = eintrag
        break
    passendeStelle["zeugnis"] = {
      "abschlussnote": float(neueNote) if neueNote else None,
      "beschreibung": neueBeschreibung
    }
    with open(buergerPfad, "w", encoding="utf-8") as file:
      json.dump(buerger, file, indent=2, ensure_ascii=False)
    messages.success(request, "Das Zeugnis wurde erfolgreich abgespeichert.")
    
  #----------------------------------------------------------------------------
  # Mitarbeiter anzeigen
  #----------------------------------------------------------------------------
  mitarbeiter = []
  bereicheSet = set()
  for stelle in arbeitgeberregister.get("stellen", []):
    if stelle.get("besetzt") and stelle.get("buerger"):
      buergerID = stelle["buerger"]
      buergerPfad = os.path.join(buergerDaten, f"{buergerID}.json")
      with open(buergerPfad, "r", encoding="utf-8") as file:
        buerger = json.load(file)
      zeugnis_beschreibung = ""
      zeugnis_note = ""
      einstellungsdatum = ""
      for eintrag in buerger.get("lebenslauf"):
        if eintrag.get("stelle") == stelle["id"]:
          zeugnis_beschreibung = eintrag.get("zeugnis").get("beschreibung")
          zeugnis_note = eintrag.get("zeugnis").get("abschlussnote")
          einstellungsdatum = eintrag.get("beginn")
          break
      #----------------------------------------------------------------------------
      # Mitarbeitername über API ermitteln
      #----------------------------------------------------------------------------
      name = buergerID
      response = requests.get(f"{API_Meldewesen_URL}/{buergerID}", timeout = 5)
      buergerStammdaten = response.json()
      vorname = buergerStammdaten.get("vorname", "").strip()
      if buergerStammdaten.get("nachname_neu", ""):
        nachname = buergerStammdaten.get("nachname_neu", "").strip()
      else:
        nachname = buergerStammdaten.get("nachname_geburt", "").strip()
      vollerName = f"{vorname} {nachname}".strip()
      if vollerName:
        name = vollerName
      mitarbeiter.append({
        'name': name,
        'bezeichnung': stelle['bezeichnung'],
        'bereiche': ", ".join(stelle['bereiche']),
        'gehalt': stelle['gehalt'],
        'einstellungsdatum': einstellungsdatum,
        'stellenID': stelle['id'],
        'buergerID': stelle['buerger'],
        'zeugnis_beschreibung': zeugnis_beschreibung,
        'abschlussnote': zeugnis_note
      })
      for bereich in stelle.get("bereiche"):
        bereicheSet.add(bereich)
  mitarbeitende_bereiche_filter_liste = sorted(list(bereicheSet))

  #----------------------------------------------------------------------------
  # Kennwortsuche und Bereichs-Filter
  #----------------------------------------------------------------------------
  filter_mitarbeitende_kennwortsuche = ""
  filter_mitarbeitende_bereich = "all"
  if request.method == "POST" and request.POST.get("aktion") not in ["entlassen", "stelle_bearbeiten", "zeugnis_bearbeiten"]:
    filter_mitarbeitende_kennwortsuche = request.POST.get("filter_mitarbeitende_kennwortsuche", "").strip()
    filter_mitarbeitende_bereich = request.POST.get("filter_mitarbeitende_bereich", "all").strip()
  gefiltert = mitarbeiter
  if filter_mitarbeitende_kennwortsuche:
    suchbegriff = filter_mitarbeitende_kennwortsuche.lower()
    neueListe = []
    for mitarbeiterEintrag in gefiltert:
      name = mitarbeiterEintrag["name"].lower()
      bezeichnung = mitarbeiterEintrag["bezeichnung"].lower()
      felder = [name, bezeichnung]
      for feld in felder:
        if suchbegriff in feld:
          neueListe.append(mitarbeiterEintrag)
          break
    gefiltert = neueListe
  if filter_mitarbeitende_bereich != "all":
    bereichFilter = filter_mitarbeitende_bereich.lower()
    neueListe = []
    for mitarbeiterEintrag in gefiltert:
      bereicheListe = mitarbeiterEintrag["bereiche"].replace(" ", "").split(",")
      for bereich in bereicheListe:
        if bereich.lower() == bereichFilter:
          neueListe.append(mitarbeiterEintrag)
          break
    gefiltert = neueListe
  

  return render(request, 'arbeitbildung/unternehmen/mitarbeiter.html', {
    'role': 'unternehmen',
    'active_page': 'unternehmen_mitarbeiter',
    'username': username,
    'mitarbeiter': gefiltert,
    'unternehmen_id': unternehmen_id,
    'filter_mitarbeitende_kennwortsuche': filter_mitarbeitende_kennwortsuche,
    'filter_mitarbeitende_bereich': filter_mitarbeitende_bereich,
    'mitarbeitende_bereiche_filter_liste': mitarbeitende_bereiche_filter_liste
  })

##############################
########## Postfach ##########
##############################

def unternehmen_postfach(request):

  unternehmen_id = request.session.get("unternehmen_id")
  username = request.session.get("unternehmen_name")
  if not unternehmen_id:
    return redirect("unternehmen/anmeldung")
  json_pfad = os.path.join(arbeitgeberData, f"{unternehmen_id}.json")

  with open(json_pfad, "r", encoding="utf-8") as file:
    arbeitgeberregister = json.load(file)

  #----------------------------------------------------------------------------
  # Nachricht(en) als geselen markieren 
  #----------------------------------------------------------------------------
  if request.method == 'POST':
    if "index" in request.POST:
      index = int(request.POST.get('index'))
      arbeitgeberregister['postfach'][index]['status'] = False
      messages.success(request, "Die Nachricht wurde als gelesen markiert.")
    elif "alle_gelesen" in request.POST:
      for eintrag in arbeitgeberregister['postfach']:
        eintrag['status'] = False
      messages.success(request, "Alle Nachrichten wurden als gelesen markiert.")
  
    with open(json_pfad, "w", encoding="utf-8") as file:
      json.dump(arbeitgeberregister, file, indent=2, ensure_ascii=False)
    
  return render(request, 'arbeitbildung/unternehmen/postfach.html', {
    'role': 'unternehmen',
    'active_page': 'unternehmen_postfach',
    'username': username,
    'postfach': arbeitgeberregister['postfach'],
    'unternehmen_id': unternehmen_id
  })