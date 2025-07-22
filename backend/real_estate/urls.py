from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create router for ViewSets
router = DefaultRouter()
router.register(r'properties', views.PropertyViewSet, basename='property')
router.register(r'regions', views.RegionViewSet, basename='region')
router.register(r'districts', views.DistrictViewSet, basename='district')

app_name = 'real_estate'

urlpatterns = [
    # Include router URLs
    path('', include(router.urls)),
    
    # User management endpoints
    path('users/create/', views.create_or_get_user, name='create-user'),
    path('users/<int:telegram_id>/language/', views.update_user_language, name='update-language'),
    path('users/<int:telegram_id>/properties/', views.user_properties, name='user-properties'),
    path('users/<int:telegram_id>/favorites/', views.user_favorites, name='user-favorites'),
    path('users/<int:telegram_id>/statistics/', views.user_statistics, name='user-statistics'),
    
    # Favorites endpoints
    path('favorites/add/', views.add_to_favorites, name='add-favorite'),
    path('favorites/remove/<int:telegram_id>/<int:property_id>/', 
         views.remove_from_favorites, name='remove-favorite'),
    
    # Legacy property endpoints (for backward compatibility)
    path('properties-list/', views.PropertyViewSet.as_view({'get': 'list'}), name='properties-list'),
    path('properties-detail/<int:pk>/', views.PropertyViewSet.as_view({'get': 'retrieve'}), name='property-detail'),
    path('properties/by-location/', views.properties_by_location, name='properties-by-location'),
    path('properties/search/', views.PropertyViewSet.as_view({'get': 'search'}), name='properties-search'),
    
    # Legacy location endpoints (for backward compatibility)
    path('regions-list/', views.regions_list, name='regions-list'),
    path('districts-list/', views.districts_list, name='districts-list'),
    path('districts-list/<int:region_id>/', views.districts_list, name='districts-by-region'),
    path('districts/region/<str:region_key>/', views.districts_by_region_key, name='districts-by-region-key'),
    
    # Statistics endpoints
    path('statistics/', views.property_statistics, name='statistics'),
    path('statistics/properties/', views.property_statistics, name='property-statistics'),
    
    # Health check
    path('health/', views.health_check, name='health-check'),
]