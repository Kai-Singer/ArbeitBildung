from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse
from django.contrib import messages
from datetime import datetime, timedelta
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
import json
import os

DATA_DIR = '/var/www/django-project/arbeitbildung/data'

##############################
########### Gehalt ###########
##############################

def api_buerger_gehalt(request, uid):
  # Bürgerdatei laden
  file_path = os.path.join(DATA_DIR, "buerger", f"{uid}.json")
  if not os.path.exists(file_path):
    return JsonResponse({"error": "User Data not found"}, status = 404)
  user_data = {}
  with open(file_path, 'r', encoding = 'utf-8') as file:
    user_data = json.loads(file.read())
  # Art der aktuellen Anstellung prüfen
  art = user_data.get("lebenslauf", [])[-1].get("art", None)
  # Prüfen, ob keine aktuelle Anstellung vorliegt
  enddatum = user_data.get("lebenslauf", [])[-1].get("ende", False)
  if enddatum != False:
    enddatum = datetime.strptime(enddatum, "%Y-%m-%d")
    jetzt = datetime.now()
    if enddatum < jetzt:
      return JsonResponse({"gehalt": 0}, status = 200)
  # Sonderfälle behandeln
  if art == None:
    return JsonResponse({"error": "Art der aktuellen Anstellung ist in der Bürgerdatei nicht angegeben"}, status = 400)
  elif art in ["schueler", "arbeitslos", "rente", "studium", "tot", "haft"]:
    return JsonResponse({"gehalt": 0}, status = 200)
  # Gehalt der Anstellung ermitteln
  unternehmenId = user_data.get("lebenslauf", [])[-1].get("arbeitgeber", None)
  stellenId = user_data.get("lebenslauf", [])[-1].get("stelle", None)
  if unternehmenId == None or stellenId == None:
    return JsonResponse({"error": "Aktuelle UnternehmensID oder StellenID sind in der Bürgerdatei nicht angegeben"}, status = 400)
  unternehmen_file_path = os.path.join(DATA_DIR, "unternehmen", f"{unternehmenId}.json")
  if not os.path.exists(unternehmen_file_path):
    return JsonResponse({"error": "Unternehmensdatei nicht gefunden"}, status = 404)
  unternehmen_data = {}
  with open(unternehmen_file_path, 'r', encoding = 'utf-8') as file:
    unternehmen_data = json.loads(file.read())
  gehalt = next((s["gehalt"] for s in unternehmen_data["stellen"] if s["id"] == stellenId), None)
  if gehalt == None:
    return JsonResponse({"error": "Gehalt der Stelle ist in der Unternehmensdatei nicht angegeben"}, status = 400)
  return JsonResponse({"gehalt": gehalt}, status = 200)

##############################
########### Beruf ############
##############################
    
def api_buerger_beruf(request, uid):
  # Bürgerdatei laden
  file_path = os.path.join(DATA_DIR, "buerger", f"{uid}.json")
  if not os.path.exists(file_path):
    return JsonResponse({"error": "Bürgerdatei nicht gefunden"}, status = 404)
  user_data = {}
  with open(file_path, 'r', encoding = 'utf-8') as file:
    user_data = json.loads(file.read())
  # Art der aktuellen Anstellung prüfen
  art = user_data.get("lebenslauf", [])[-1].get("art", None)
  # Prüfen, ob keine aktuelle Anstellung vorliegt
  enddatum = user_data.get("lebenslauf", [])[-1].get("ende", False)
  if enddatum != False:
    enddatum = datetime.strptime(enddatum, "%Y-%m-%d")
    jetzt = datetime.now()
    if enddatum < jetzt:
      return JsonResponse({"error": "Der Bürger besitzt aktuell keine Tätigkeit jeglicher Art"}, status = 400)
  # Sonderfälle behandeln
  if art == None:
    return JsonResponse({"error": "Art der aktuellen Anstellung ist in der Bürgerdatei nicht angegeben"}, status = 400)
  elif art == "schueler":
    return JsonResponse({"beruf": "Schüler"}, status = 200)
  elif art == "arbeitslos":
    return JsonResponse({"beruf": "arbeitslos"}, status = 200)
  elif art == "rente":
    return JsonResponse({"beruf": "Rente"}, status = 200)
  elif art == "tot":
    return JsonResponse({"beruf": "tot"}, status = 200)
  elif art == "haft":
    return JsonResponse({"beruf": "in Haft"}, status = 200)
  # Beruf der Anstellung ermitteln
  unternehmenId = user_data.get("lebenslauf", [])[-1].get("arbeitgeber", None)
  stellenId = user_data.get("lebenslauf", [])[-1].get("stelle", None)
  if unternehmenId == None or stellenId == None:
    return JsonResponse({"error": "Aktuelle UnternehmensID oder StellenID sind in der Bürgerdatei nicht angegeben"}, status = 400)
  unternehmen_file_path = os.path.join(DATA_DIR, "unternehmen", f"{unternehmenId}.json")
  if not os.path.exists(unternehmen_file_path):
    return JsonResponse({"error": "Unternehmensdatei nicht gefunden"}, status = 404)
  unternehmen_data = {}
  with open(unternehmen_file_path, 'r', encoding = 'utf-8') as file:
    unternehmen_data = json.loads(file.read())
  bezeichnung = next((s["bezeichnung"] for s in unternehmen_data["stellen"] if s["id"] == stellenId), None)
  if bezeichnung == None:
    return JsonResponse({"error": "Bezeichnung der Stelle ist in der Unternehmensdatei nicht angegeben"}, status = 400)
  return JsonResponse({"beruf": bezeichnung}, status = 200)
    
##############################
####### Personenliste ########
##############################

def api_personenliste(request, beruf):
  # Alle Bürgerdateien durchsuchen
  personen_liste = []
  buerger_dir = os.path.join(DATA_DIR, "buerger")
  for filename in os.listdir(buerger_dir):
    if filename.endswith(".json"):
      file_path = os.path.join(buerger_dir, filename)
      with open(file_path, 'r', encoding = 'utf-8') as file:
        user_data = json.loads(file.read())
        lebenslauf = user_data.get("lebenslauf", [])
        # Art der aktuellen Anstellung ermitteln
        art = lebenslauf[-1].get("art", None) if lebenslauf else None
        # Prüfen, ob keine aktuelle Anstellung vorliegt
        enddatum = lebenslauf[-1].get("ende", False) if lebenslauf else False
        if enddatum != False:
          enddatum = datetime.strptime(enddatum, "%Y-%m-%d")
          jetzt = datetime.now()
          if enddatum < jetzt:
            continue
        # Sonderfälle behandeln
        if beruf == "schueler" and art == "schueler":
          personen_liste.append({
            "uid": user_data.get("id", None)
          })
        elif beruf == "studium" and art == "studium":
          personen_liste.append({
            "uid": user_data.get("id", None)
          })
        elif beruf == "duales_studium" and art == "duales_studium":
          personen_liste.append({
            "uid": user_data.get("id", None)
          })
        elif beruf == "ausbildung" and art == "ausbildung":
          personen_liste.append({
            "uid": user_data.get("id", None)
          })
        elif beruf == "tot" and art == "tot":
          personen_liste.append({
            "uid": user_data.get("id", None)
          })
        elif beruf == "haft" and art == "haft":
          personen_liste.append({
            "uid": user_data.get("id", None)
          })
        # Letztes Gehalt für Arbeitslosigkeit ermitteln
        elif beruf == "arbeitslos" and art == "arbeitslos":
          mainLetztesGehalt = 0
          for entry in reversed(user_data.get("lebenslauf", [])):
            if entry.get("art", None) in ["anstellung", "duales_studium", "ausbildung"]:
              stellenId = entry.get("stelle", None)
              unternehmenId = entry.get("arbeitgeber", None)
              if stellenId != None and unternehmenId != None:
                unternehmen_file_path = os.path.join(DATA_DIR, "unternehmen", f"{unternehmenId}.json")
                if os.path.exists(unternehmen_file_path):
                  with open(unternehmen_file_path, 'r', encoding = 'utf-8') as u_file:
                    unternehmen_data = json.loads(u_file.read())
                    letztesGehalt = next((s["gehalt"] for s in unternehmen_data["stellen"] if s["id"] == stellenId), 0)
                    if letztesGehalt != 0:
                      mainLetztesGehalt = letztesGehalt
                      break
          personen_liste.append({
            "uid": user_data.get("id", None),
            "letztes_gehalt": mainLetztesGehalt
          })
        # Letztes Gehalt für Rente ermitteln
        elif beruf == "rente" and art == "rente":
          mainLetztesGehalt = 0
          for entry in reversed(user_data.get("lebenslauf", [])):
            if entry.get("art", None) in ["anstellung", "duales_studium", "ausbildung"]:
              stellenId = entry.get("stelle", None)
              unternehmenId = entry.get("arbeitgeber", None)
              if stellenId != None and unternehmenId != None:
                unternehmen_file_path = os.path.join(DATA_DIR, "unternehmen", f"{unternehmenId}.json")
                if os.path.exists(unternehmen_file_path):
                  with open(unternehmen_file_path, 'r', encoding = 'utf-8') as u_file:
                    unternehmen_data = json.loads(u_file.read())
                    letztesGehalt = next((s["gehalt"] for s in unternehmen_data["stellen"] if s["id"] == stellenId), 0)
                    if letztesGehalt != 0:
                      mainLetztesGehalt = letztesGehalt
                      break
          personen_liste.append({
            "uid": user_data.get("id", None),
            "letztes_gehalt": mainLetztesGehalt
          })
        # Berufliche Anstellung ermitteln
        else:
          if art == "anstellung":
            unternehmenId = user_data.get("lebenslauf", [])[-1].get("arbeitgeber", None)
            stellenId = user_data.get("lebenslauf", [])[-1].get("stelle", None)
            if unternehmenId != None and stellenId != None:
              unternehmen_file_path = os.path.join(DATA_DIR, "unternehmen", f"{unternehmenId}.json")
              if os.path.exists(unternehmen_file_path):
                with open(unternehmen_file_path, 'r', encoding = 'utf-8') as u_file:
                  unternehmen_data = json.loads(u_file.read())
                  bezeichnung = next((s["bezeichnung"] for s in unternehmen_data["stellen"] if s["id"] == stellenId), None)
                  if bezeichnung.lower() == beruf:
                    if beruf == "arzt":
                      personen_liste.append({
                        "uid": user_data.get("id", None),
                        "arbeitgeber": unternehmen_data.get("name", None),
                        "adresse": unternehmen_data.get("adresse", None)
                      })
                    else:
                      personen_liste.append({
                        "uid": user_data.get("id", None)
                      })
  return JsonResponse({"personen": personen_liste}, status = 200)