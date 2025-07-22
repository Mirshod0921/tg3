# backend/real_estate/apps.py (corrected)
from django.apps import AppConfig

class RealEstateConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'real_estate'
    verbose_name = 'Real Estate Management'

    def ready(self):
        # Import admin customizations
        try:
            from . import admin
        except ImportError:
            pass
        
        # Set up admin site
        from django.contrib import admin as django_admin
        django_admin.site.site_header = "Real Estate Bot Administration"
        django_admin.site.site_title = "Real Estate Bot Admin"
        django_admin.site.index_title = "Dashboard"
        
        # Register signal handlers
        try:
            import real_estate.signals
        except ImportError:
            pass