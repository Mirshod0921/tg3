"""
URL configuration for real_estate_project project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.views.generic import TemplateView
from rest_framework.documentation import include_docs_urls

def api_root(request):
    """API root endpoint with available endpoints"""
    return JsonResponse({
        'message': 'Real Estate Bot API',
        'version': '1.0.0',
        'endpoints': {
            'admin': '/admin/',
            'api': '/api/',
            'docs': '/docs/',
            'health': '/api/health/',
            'users': '/api/users/',
            'properties': '/api/properties/',
            'regions': '/api/regions/',
            'districts': '/api/districts/',
            'favorites': '/api/favorites/',
            'statistics': '/api/statistics/',
            'payments': '/payments/',
        },
        'swagger': '/docs/',
        'admin_panel': '/admin/',
    })

urlpatterns = [
    # Admin panel
    path('admin/', admin.site.urls),
    
    # API root
    path('', api_root, name='api-root'),
    
    # API endpoints
    path('api/', include('real_estate.urls', namespace='real_estate')),
    path('payments/', include('payments.urls', namespace='payments')),
    
    # API Documentation
#    path('docs/', include_docs_urls(
#        title='Real Estate Bot API',
#        description='API documentation for Real Estate Telegram Bot'
#    )),
    
    # Health check at root level
    path('health/', include('real_estate.urls')),
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