from django.urls import path
from arbeitbildung import views

urlpatterns = [
    # Kai Singer
    ### APIs ###
    path('api/buerger/gehalt/<str:uid>', views.api_buerger_gehalt, name = 'api/buerger/gehalt'),
    path('api/buerger/beruf/<str:uid>', views.api_buerger_beruf, name = 'api/buerger/beruf'),
    path('api/personenliste/<str:beruf>', views.api_personenliste, name = 'api/personenliste'),

    ### Allgemein ###
    path('struktur_vorlage', views.struktur_vorlage, name = 'struktur_vorlage'),
    path('', views.home, name = 'home'),
    # Louis Raisch
    path('logout', views.logout, name = 'logout'),
    path("jwt-login", views.jwt_login, name="jwt_login"),

    # Louis Raisch
    ### Bürger ###
    path('buerger/dashboard', views.buerger_dashboard, name = 'buerger/dashboard'),
    path('buerger/lebenslauf', views.buerger_lebenslauf, name = 'buerger/lebenslauf'),
    path('buerger/lebenslauf/download/', views.buerger_lebenslauf_download, name='buerger_lebenslauf_download'),
    # Kai Singer
    path('buerger/jobboerse', views.buerger_jobboerse, name = 'buerger/jobboerse'),
    path('buerger/bewerbungen', views.buerger_bewerbungen, name = 'buerger/bewerbungen'),
    # Louis Raisch
    path('buerger/postfach', views.buerger_postfach, name = 'buerger/postfach'),
    path('buerger/session_anzeigen', views.session_anzeigen, name = 'buerger/session_anzeigen'),

    # Leonie Waimer
    ### Unternehmen ###
    path('unternehmen/dashboard', views.unternehmen_dashboard, name = 'unternehmen/dashboard'),
    path('unternehmen/bewerber', views.unternehmen_bewerber, name = 'unternehmen/bewerber'),
    path('unternehmen/mitarbeiter', views.unternehmen_mitarbeiter, name = 'unternehmen/mitarbeiter'),
    path('unternehmen/postfach', views.unternehmen_postfach, name = 'unternehmen/postfach'),
    path('unternehmen/anmeldung', views.unternehmen_anmeldung, name = 'unternehmen/anmeldung'),
    path('unternehmen/registrierung', views.unternehmen_registrierung, name = 'unternehmen/registrierung'),
    path('unternehmen/weiterleitungKasse', views.weiterleitungKasse, name='unternehmen/weiterleitungKasse'),

    # Sophie Schumann
    ### Bildungseinrichtungen ###
    path('bildungseinrichtungen/dashboard', views.bildungseinrichtungen_dashboard, name = 'bildungseinrichtungen/dashboard'),
    path('bildungseinrichtungen/schueler', views.bildungseinrichtungen_schueler, name = 'bildungseinrichtungen/schueler'),
    path('bildungseinrichtungen/postfach', views.bildungseinrichtungen_postfach, name = 'bildungseinrichtungen/postfach'),
    path('bildungseinrichtungen/anmeldung', views.bildungseinrichtungen_anmeldung, name = 'bildungseinrichtungen/anmeldung'),
    path('bildungseinrichtungen/registrierung', views.bildungseinrichtungen_registrierung, name = 'bildungseinrichtungen/registrierung'),

    # Louis Raisch
    ### Admin ###
    path('admin/dashboard', views.admin_dashboard, name = 'admin/dashboard'),
    path('admin/statistiken', views.admin_statistiken, name = 'admin/statistiken'),
    path('admin/postfach', views.admin_postfach, name = 'admin/postfach'),
    path('admin/anmeldung', views.admin_anmeldung, name = 'admin/anmeldung'),

]
