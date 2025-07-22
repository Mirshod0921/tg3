# backend/real_estate_project/urls.py - Fixed namespace issue
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

def api_root(request):
    """API root endpoint with available endpoints"""
    return JsonResponse({
        'message': 'Real Estate Bot API',
        'version': '1.0.0',
        'endpoints': {
            'admin': '/admin/',
            'api': '/api/',
            'health': '/api/health/',
            'users': '/api/users/',
            'properties': '/api/properties/',
            'regions': '/api/regions/',
            'districts': '/api/districts/',
            'favorites': '/api/favorites/',
            'statistics': '/api/statistics/',
            'payments': '/payments/',
        },
        'admin_panel': '/admin/',
    })

urlpatterns = [
    # Admin panel
    path('admin/', admin.site.urls),
    
    # API root
    path('', api_root, name='api-root'),
    
    # API endpoints with unique namespace
    path('api/', include('real_estate.urls', namespace='api')),
    path('payments/', include('payments.urls', namespace='payments')),
    
    # Health check at root level
    path('health/', include(('real_estate.urls', 'real_estate'), namespace='health')),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
    # Add debug toolbar if available
    try:
        import debug_toolbar
        urlpatterns = [
            path('__debug__/', include(debug_toolbar.urls)),
        ] + urlpatterns
    except ImportError:
        pass

# Custom error handlers
handler404 = 'real_estate_project.views.handler404'
handler500 = 'real_estate_project.views.handler500'