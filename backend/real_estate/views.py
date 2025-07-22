from rest_framework import generics, status, filters
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import rest_framework as filters_rf
from django.db.models import Q, Count, Avg, Sum
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from datetime import datetime, timedelta
import logging
from django.db import models
from .models import (
    TelegramUser, Property, Favorite, UserActivity, 
    Region, District, SearchQuery
)
from .serializers import (
    TelegramUserSerializer, PropertySerializer, PropertyListSerializer,
    FavoriteSerializer, UserActivitySerializer, RegionSerializer, 
    DistrictSerializer, PropertyDetailSerializer
)

logger = logging.getLogger(__name__)

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

class PropertyFilter(filters_rf.FilterSet):
    min_price = filters_rf.NumberFilter(field_name="price", lookup_expr='gte')
    max_price = filters_rf.NumberFilter(field_name="price", lookup_expr='lte')
    min_area = filters_rf.NumberFilter(field_name="area", lookup_expr='gte')
    max_area = filters_rf.NumberFilter(field_name="area", lookup_expr='lte')
    min_rooms = filters_rf.NumberFilter(field_name="rooms", lookup_expr='gte')
    max_rooms = filters_rf.NumberFilter(field_name="rooms", lookup_expr='lte')
    region = filters_rf.CharFilter(field_name="region", lookup_expr='exact')
    district = filters_rf.CharFilter(field_name="district", lookup_expr='exact')
    created_after = filters_rf.DateTimeFilter(field_name="created_at", lookup_expr='gte')
    created_before = filters_rf.DateTimeFilter(field_name="created_at", lookup_expr='lte')
    
    class Meta:
        model = Property
        fields = [
            'property_type', 'status', 'condition', 'region', 'district', 
            'is_premium', 'min_price', 'max_price', 'min_area', 'max_area',
            'min_rooms', 'max_rooms', 'created_after', 'created_before'
        ]

# User Management Views
@api_view(['POST'])
@permission_classes([AllowAny])
def create_or_get_user(request):
    """Create or get Telegram user"""
    try:
        telegram_id = request.data.get('telegram_id')
        if not telegram_id:
            return Response(
                {'error': 'telegram_id is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user, created = TelegramUser.objects.get_or_create(
            telegram_id=telegram_id,
            defaults={
                'username': request.data.get('username', ''),
                'first_name': request.data.get('first_name', ''),
                'last_name': request.data.get('last_name', ''),
                'language': request.data.get('language', 'uz'),
                'is_blocked': False,
                'balance': 0.00
            }
        )
        
        if not created:
            # Update user info if provided
            update_fields = []
            for field in ['username', 'first_name', 'last_name', 'language']:
                if field in request.data:
                    setattr(user, field, request.data[field])
                    update_fields.append(field)
            
            if update_fields:
                user.save(update_fields=update_fields + ['updated_at'])
        
        # Log user activity
        UserActivity.objects.create(
            user=user,
            action='start' if created else 'return',
            details={'new_user': created}
        )
        
        serializer = TelegramUserSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error creating/getting user: {e}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['PUT'])
@permission_classes([AllowAny])
def update_user_language(request, telegram_id):
    """Update user language"""
    try:
        user = get_object_or_404(TelegramUser, telegram_id=telegram_id)
        language = request.data.get('language')
        
        if language and language in ['uz', 'ru', 'en']:
            user.language = language
            user.save(update_fields=['language', 'updated_at'])
            
            # Log activity
            UserActivity.objects.create(
                user=user,
                action='language_change',
                details={'new_language': language}
            )
            
            serializer = TelegramUserSerializer(user)
            return Response(serializer.data)
        
        return Response(
            {'error': 'Invalid language'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
        
    except Exception as e:
        logger.error(f"Error updating user language: {e}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# Property Views
class PropertyViewSet(ModelViewSet):
    """Complete CRUD operations for properties"""
    serializer_class = PropertySerializer
    permission_classes = [AllowAny]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PropertyFilter
    search_fields = ['title', 'description', 'address', 'full_address', 'contact_info']
    ordering_fields = ['created_at', 'price', 'area', 'views_count', 'favorites_count']
    ordering = ['-is_premium', '-created_at']
    
    def get_queryset(self):
        queryset = Property.objects.select_related('user').prefetch_related('favorited_by')
        
        # Filter by approval status
        if self.action == 'list':
            queryset = queryset.filter(is_approved=True, is_active=True)
        
        # Additional filters from query params
        user_id = self.request.query_params.get('user_id')
        if user_id:
            try:
                user = TelegramUser.objects.get(telegram_id=user_id)
                queryset = queryset.filter(user=user)
            except TelegramUser.DoesNotExist:
                pass
        
        return queryset
    
    def get_serializer_class(self):
        if self.action == 'list':
            return PropertyListSerializer
        elif self.action == 'retrieve':
            return PropertyDetailSerializer
        return PropertySerializer
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # Increment view count
        instance.increment_views()
        
        # Log activity if user is provided
        user_id = request.query_params.get('user_id')
        if user_id:
            try:
                user = TelegramUser.objects.get(telegram_id=user_id)
                UserActivity.objects.create(
                    user=user,
                    action='view_listing',
                    property=instance
                )
            except TelegramUser.DoesNotExist:
                pass
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
    
    def create(self, request, *args, **kwargs):
        try:
            user_id = request.data.get('user_id')
            if not user_id:
                return Response(
                    {'error': 'user_id is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            user = get_object_or_404(TelegramUser, telegram_id=user_id)
            
            # Create property
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            property_instance = serializer.save(user=user)
            
            # Log activity
            UserActivity.objects.create(
                user=user,
                action='post_listing',
                property=property_instance
            )
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating property: {e}")
            return Response(
                {'error': 'Internal server error'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def by_location(self, request):
        """Get properties filtered by region and/or district"""
        region_key = request.query_params.get('region')
        district_key = request.query_params.get('district')
        
        queryset = self.get_queryset()
        
        if region_key:
            queryset = queryset.filter(region=region_key)
        
        if district_key:
            queryset = queryset.filter(district=district_key)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PropertyListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = PropertyListSerializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def search(self, request):
        """Advanced search with logging"""
        query = request.query_params.get('q', '').strip()
        search_type = request.query_params.get('type', 'keyword')
        user_id = request.query_params.get('user_id')
        
        if not query:
            return Response({'error': 'Search query is required'}, status=400)
        
        queryset = self.get_queryset()
        
        if search_type == 'keyword':
            queryset = queryset.filter(
                Q(title__icontains=query) |
                Q(description__icontains=query) |
                Q(address__icontains=query) |
                Q(full_address__icontains=query)
            )
        
        results_count = queryset.count()
        
        # Log search query
        user = None
        if user_id:
            try:
                user = TelegramUser.objects.get(telegram_id=user_id)
            except TelegramUser.DoesNotExist:
                pass
        
        SearchQuery.objects.create(
            user=user,
            query=query,
            search_type=search_type,
            results_count=results_count
        )
        
        # Log user activity
        if user:
            UserActivity.objects.create(
                user=user,
                action='search',
                details={'query': query, 'results_count': results_count}
            )
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PropertyListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = PropertyListSerializer(queryset, many=True)
        return Response(serializer.data)

# Favorites Views
@api_view(['POST'])
@permission_classes([AllowAny])
def add_to_favorites(request):
    """Add property to favorites"""
    try:
        telegram_id = request.data.get('user_id')
        property_id = request.data.get('property_id')
        
        if not telegram_id or not property_id:
            return Response(
                {'error': 'user_id and property_id are required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user = get_object_or_404(TelegramUser, telegram_id=telegram_id)
        property_obj = get_object_or_404(Property, id=property_id)
        
        favorite, created = Favorite.objects.get_or_create(
            user=user,
            property=property_obj
        )
        
        if created:
            # Log activity
            UserActivity.objects.create(
                user=user,
                action='favorite_add',
                property=property_obj
            )
            
            return Response(
                {'message': 'Added to favorites'}, 
                status=status.HTTP_201_CREATED
            )
        else:
            return Response(
                {'message': 'Already in favorites'}, 
                status=status.HTTP_200_OK
            )
    
    except Exception as e:
        logger.error(f"Error adding to favorites: {e}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['DELETE'])
@permission_classes([AllowAny])
def remove_from_favorites(request, telegram_id, property_id):
    """Remove property from favorites"""
    try:
        user = get_object_or_404(TelegramUser, telegram_id=telegram_id)
        favorite = get_object_or_404(Favorite, user=user, property_id=property_id)
        
        # Log activity before deletion
        UserActivity.objects.create(
            user=user,
            action='favorite_remove',
            property=favorite.property
        )
        
        favorite.delete()
        
        return Response(
            {'message': 'Removed from favorites'}, 
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Error removing from favorites: {e}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([AllowAny])
def user_favorites(request, telegram_id):
    """Get user's favorites"""
    try:
        user = get_object_or_404(TelegramUser, telegram_id=telegram_id)
        favorites = Favorite.objects.filter(user=user).select_related('property__user').order_by('-created_at')
        
        # Paginate results
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(favorites, request)
        
        if page is not None:
            serializer = FavoriteSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = FavoriteSerializer(favorites, many=True)
        return Response(serializer.data)
        
    except Exception as e:
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([AllowAny])
def user_properties(request, telegram_id):
    """Get user's properties"""
    try:
        user = get_object_or_404(TelegramUser, telegram_id=telegram_id)
        properties = Property.objects.filter(user=user).order_by('-created_at')
        
        # Paginate results
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(properties, request)
        
        if page is not None:
            serializer = PropertyListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = PropertyListSerializer(properties, many=True)
        return Response(serializer.data)
        
    except Exception as e:
        logger.error(f"Error getting user properties: {e}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# Location Views
class RegionViewSet(ReadOnlyModelViewSet):
    """Read-only operations for regions"""
    queryset = Region.objects.filter(is_active=True).order_by('order', 'name_uz')
    serializer_class = RegionSerializer
    permission_classes = [AllowAny]
    
    @action(detail=True, methods=['get'])
    def districts(self, request, pk=None):
        """Get districts for a specific region"""
        region = self.get_object()
        districts = District.objects.filter(region=region, is_active=True).order_by('order', 'name_uz')
        serializer = DistrictSerializer(districts, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def with_counts(self, request):
        """Get regions with property counts"""
        regions = Region.objects.filter(is_active=True).annotate(
            properties_count=Count('districts__key', filter=Q(
                districts__key__in=Property.objects.filter(
                    is_approved=True, is_active=True
                ).values_list('region', flat=True)
            ))
        ).order_by('order', 'name_uz')
        
        serializer = RegionSerializer(regions, many=True)
        return Response(serializer.data)

class DistrictViewSet(ReadOnlyModelViewSet):
    """Read-only operations for districts"""
    queryset = District.objects.filter(is_active=True).select_related('region').order_by('region__order', 'order', 'name_uz')
    serializer_class = DistrictSerializer
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        region_id = self.request.query_params.get('region_id')
        region_key = self.request.query_params.get('region_key')
        
        if region_id:
            queryset = queryset.filter(region_id=region_id)
        elif region_key:
            queryset = queryset.filter(region__key=region_key)
        
        return queryset

# Legacy API endpoints for backward compatibility
@api_view(['GET'])
@permission_classes([AllowAny])
def regions_list(request):
    """Get list of regions"""
    regions = Region.objects.filter(is_active=True).order_by('order', 'name_uz')
    serializer = RegionSerializer(regions, many=True)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([AllowAny])
def districts_list(request, region_id=None):
    """Get list of districts, optionally filtered by region"""
    if region_id:
        districts = District.objects.filter(region_id=region_id, is_active=True)
    else:
        districts = District.objects.filter(is_active=True)
    
    districts = districts.select_related('region').order_by('region__order', 'order', 'name_uz')
    serializer = DistrictSerializer(districts, many=True)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([AllowAny])
def districts_by_region_key(request, region_key):
    """Get districts by region key"""
    try:
        region = get_object_or_404(Region, key=region_key, is_active=True)
        districts = District.objects.filter(region=region, is_active=True).order_by('order', 'name_uz')
        serializer = DistrictSerializer(districts, many=True)
        return Response(serializer.data)
    except Exception as e:
        logger.error(f"Error getting districts by region key: {e}")
        return Response(
            {'error': 'Region not found'}, 
            status=status.HTTP_404_NOT_FOUND
        )

@api_view(['GET'])
@permission_classes([AllowAny])
def properties_by_location(request):
    """Get properties filtered by region and/or district"""
    try:
        region_key = request.GET.get('region')
        district_key = request.GET.get('district')
        
        queryset = Property.objects.filter(is_approved=True, is_active=True).select_related('user')
        
        if region_key:
            queryset = queryset.filter(region=region_key)
        
        if district_key:
            queryset = queryset.filter(district=district_key)
        
        queryset = queryset.order_by('-is_premium', '-created_at')
        
        # Paginate results
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset, request)
        
        if page is not None:
            serializer = PropertyListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = PropertyListSerializer(queryset, many=True)
        return Response(serializer.data)
        
    except Exception as e:
        logger.error(f"Error getting properties by location: {e}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# Statistics and Analytics Views
@api_view(['GET'])
@permission_classes([AllowAny])
def property_statistics(request):
    """Get comprehensive property statistics"""
    try:
        # Basic counts
        total_properties = Property.objects.filter(is_approved=True).count()
        active_properties = Property.objects.filter(is_approved=True, is_active=True).count()
        premium_properties = Property.objects.filter(is_approved=True, is_premium=True).count()
        
        # Time-based statistics
        now = timezone.now()
        today = now.date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        properties_today = Property.objects.filter(
            is_approved=True, created_at__date=today
        ).count()
        
        properties_this_week = Property.objects.filter(
            is_approved=True, created_at__gte=week_ago
        ).count()
        
        properties_this_month = Property.objects.filter(
            is_approved=True, created_at__gte=month_ago
        ).count()
        
        # Category statistics
        properties_by_type = list(
            Property.objects.filter(is_approved=True)
            .values('property_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        
        properties_by_status = list(
            Property.objects.filter(is_approved=True)
            .values('status')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        
        # Regional statistics
        properties_by_region = []
        for region in Region.objects.filter(is_active=True):
            count = Property.objects.filter(
                is_approved=True, region=region.key
            ).count()
            if count > 0:
                properties_by_region.append({
                    'region_key': region.key,
                    'region_name': region.name_uz,
                    'count': count
                })
        
        properties_by_region = sorted(properties_by_region, key=lambda x: x['count'], reverse=True)
        
        # Price statistics
        price_stats = Property.objects.filter(is_approved=True).aggregate(
            avg_price=Avg('price'),
            min_price=models.Min('price'),
            max_price=models.Max('price')
        )
        
        # User statistics
        total_users = TelegramUser.objects.count()
        active_users = TelegramUser.objects.filter(
            activities__created_at__gte=week_ago
        ).distinct().count()
        
        # Recent properties
        recent_properties = Property.objects.filter(
            is_approved=True, is_active=True
        ).select_related('user').order_by('-created_at')[:5]
        
        recent_properties_data = PropertyListSerializer(recent_properties, many=True).data
        
        # Popular searches
        popular_searches = list(
            SearchQuery.objects.filter(created_at__gte=week_ago)
            .values('query')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        
        stats = {
            # Basic counts
            'total_properties': total_properties,
            'active_properties': active_properties,
            'premium_properties': premium_properties,
            'total_users': total_users,
            'active_users': active_users,
            
            # Time-based
            'properties_today': properties_today,
            'properties_this_week': properties_this_week,
            'properties_this_month': properties_this_month,
            
            # Categories
            'properties_by_type': properties_by_type,
            'properties_by_status': properties_by_status,
            'properties_by_region': properties_by_region[:10],  # Top 10 regions
            
            # Price statistics
            'price_statistics': price_stats,
            
            # Recent data
            'recent_properties': recent_properties_data,
            'popular_searches': popular_searches,
            
            # Ratios and percentages
            'premium_percentage': round((premium_properties / total_properties * 100) if total_properties > 0 else 0, 2),
            'active_percentage': round((active_properties / total_properties * 100) if total_properties > 0 else 0, 2),
        }
        
        return Response(stats)
        
    except Exception as e:
        logger.error(f"Error getting property statistics: {e}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@permission_classes([AllowAny])
def user_statistics(request, telegram_id):
    """Get statistics for a specific user"""
    try:
        user = get_object_or_404(TelegramUser, telegram_id=telegram_id)
        
        # User's properties statistics
        user_properties = Property.objects.filter(user=user)
        total_properties = user_properties.count()
        approved_properties = user_properties.filter(is_approved=True).count()
        premium_properties = user_properties.filter(is_premium=True).count()
        
        # Views and favorites
        total_views = user_properties.aggregate(total_views=Sum('views_count'))['total_views'] or 0
        total_favorites = user_properties.aggregate(total_favorites=Sum('favorites_count'))['total_favorites'] or 0
        
        # User's favorites
        user_favorites = Favorite.objects.filter(user=user).count()
        
        # Recent activity
        recent_activities = UserActivity.objects.filter(user=user).order_by('-created_at')[:10]
        
        stats = {
            'user_info': TelegramUserSerializer(user).data,
            'properties': {
                'total': total_properties,
                'approved': approved_properties,
                'premium': premium_properties,
                'pending': total_properties - approved_properties,
            },
            'engagement': {
                'total_views': total_views,
                'total_favorites': total_favorites,
                'user_favorites': user_favorites,
            },
            'recent_activities': UserActivitySerializer(recent_activities, many=True).data,
        }
        
        return Response(stats)
        
    except Exception as e:
        logger.error(f"Error getting user statistics: {e}")
        return Response(
            {'error': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# Health check endpoint
@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """Simple health check endpoint"""
    try:
        # Test database connection
        user_count = TelegramUser.objects.count()
        property_count = Property.objects.count()
        
        return Response({
            'status': 'healthy',
            'timestamp': timezone.now(),
            'database': 'connected',
            'users': user_count,
            'properties': property_count
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return Response({
            'status': 'unhealthy',
            'timestamp': timezone.now(),
            'error': str(e)
        }, status=500)