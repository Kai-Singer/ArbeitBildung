from django.contrib import admin
from django.urls import include, path
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

urlpatterns = [
    # path('', include('dvmplanner.urls'))
    # path('', include('testsApp.urls'))
    # path('', include('burgerkarte.urls'))
    path('', include('arbeitbildung.urls'))
]

urlpatterns += staticfiles_urlpatterns()
