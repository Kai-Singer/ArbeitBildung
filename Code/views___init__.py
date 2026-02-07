from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse, HttpResponse
from django.contrib import messages
from datetime import datetime, timedelta
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
import json
import os
from urllib.parse import quote
from project.jwt_tooling import create_jwt, decode_jwt


from .buerger import *
from .unternehmen import *
from .bildungseinrichtungen import *
from .admin import *
from .api import *

DATA_DIR = '/var/www/django-project/arbeitbildung/data'

# Louis Raisch

##############################
#### Sessionübertragung ######
##############################


def jwt_login(request):
    token = request.GET.get("token")
    if not token:
        return HttpResponse("Kein Token übergeben.", status=400)

    daten = decode_jwt(token)
    if daten is None:
        return HttpResponse("Ungültiges oder abgelaufenes Token.", status=401)

    buerger_id = daten["user_id"]

    # Session erstellen
    request.session["buerger_id"] = buerger_id

    # Dashboard weiterleitung
    return redirect("/buerger/dashboard")

def weiterleitungKasse(request):
  unternehmenID = request.session.get("unternehmen_id")
  if not unternehmenID:
    return HttpResponse("Nicht eingeloggt!", status=401)
  token = create_jwt(unternehmenID)
  redirect_url = (
      "http://[2001:7c0:2320:2:f816:3eff:fe82:34b2]:8000" 
      f"/jwt-login?token={quote(token)}"
    )
  return redirect(redirect_url)

# Kai Singer

##############################
##### Struktur-Vorlage #######
##############################

def struktur_vorlage(request):
  return render(request, 'arbeitbildung/struktur_vorlage.html', {
    'role': 'buerger',
    'active_page': 'buerger_dashboard',
    'username': 'Max Mustermann'
  })

##############################
############ Home ############
##############################

def home(request):
  return redirect('buerger/dashboard')

# Louis Raisch

##############################
########### Logout ###########
##############################



TARGET_URL = "[2001:7c0:2320:2:f816:3eff:fef8:f5b9]:8000" #Zieladresse!

def weiterleitung_Mainpage(request):
    buerger_id = request.session.get("buerger_id")
    if not buerger_id:
        return HttpResponse("Nicht eingeloggt!", status=401)

    token = create_jwt(buerger_id)
    redirect_url = f"{TARGET_URL}/jwt-login?token={quote(token)}"
    return redirect(redirect_url)

def logout(request):
  role = request.GET.get('role', 'buerger')
  request.session.flush()
  if role == 'unternehmen':
    return redirect('unternehmen/anmeldung')
  elif role == 'bildungseinrichtungen':
    return redirect('bildungseinrichtungen/anmeldung')
  elif role == 'admin':
    return redirect('admin/anmeldung')
  else:
    return redirect('http://[2001:7c0:2320:2:f816:3eff:fef8:f5b9]:8000/einwohnermeldeamt/mainpage')