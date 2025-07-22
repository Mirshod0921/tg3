from rest_framework import serializers
from django.utils import timezone
from .models import (
    TelegramUser, Property, Favorite, UserActivity, 
    Region, District, PropertyImage, SearchQuery
)

class TelegramUserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    properties_count = serializers.SerializerMethodField()
    favorites_count = serializers.SerializerMethodField()
    is_premium_active = serializers.BooleanField(source='is_premium_active', read_only=True)
    
    class Meta:
        model = TelegramUser
        fields = [
            'id', 'telegram_id', 'username', 'first_name', 'last_name', 'full_name',
            'language', 'is_blocked', 'balance', 'is_premium', 'is_premium_active',
            'premium_expires_at', 'properties_count', 'favorites_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'full_name', 'is_premium_active']
    
    def get_properties_count(self, obj):
        return obj.properties.count()
    
    def get_favorites_count(self, obj):
        return obj.favorites.count()

class RegionSerializer(serializers.ModelSerializer):
    properties_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Region
        fields = [
            'id', 'name_uz', 'name_ru', 'name_en', 'key', 
            'is_active', 'order', 'properties_count'
        ]
    
    def get_properties_count(self, obj):
        return Property.objects.filter(region=obj.key, is_approved=True).count()

class DistrictSerializer(serializers.ModelSerializer):
    region_name = serializers.CharField(source='region.name_uz', read_only=True)
    region_key = serializers.CharField(source='region.key', read_only=True)
    properties_count = serializers.SerializerMethodField()
    
    class Meta:
        model = District
        fields = [
            'id', 'name_uz', 'name_ru', 'name_en', 'key',
            'region', 'region_name', 'region_key', 'is_active', 
            'order', 'properties_count'
        ]
    
    def get_properties_count(self, obj):
        return Property.objects.filter(
            region=obj.region.key, 
            district=obj.key, 
            is_approved=True
        ).count()

class PropertyImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyImage
        fields = [
            'id', 'telegram_file_id', 'file_size', 'width', 'height',
            'order', 'is_main', 'uploaded_at'
        ]

class PropertyListSerializer(serializers.ModelSerializer):
    """Serializer for property list view (minimal data)"""
    user_name = serializers.SerializerMethodField()
    user_username = serializers.CharField(source='user.username', read_only=True)
    first_photo_id = serializers.CharField(source='get_first_photo_id', read_only=True)
    location_display = serializers.SerializerMethodField()
    price_formatted = serializers.SerializerMethodField()
    property_type_display = serializers.CharField(source='get_property_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_favorited = serializers.SerializerMethodField()
    days_ago = serializers.SerializerMethodField()
    
    class Meta:
        model = Property
        fields = [
            'id', 'title', 'price', 'price_formatted', 'area', 'rooms', 
            'property_type', 'property_type_display', 'status', 'status_display',
            'address', 'full_address', 'location_display', 'region', 'district',
            'is_premium', 'views_count', 'favorites_count', 'user_name', 
            'user_username', 'first_photo_id', 'is_favorited', 'days_ago',
            'created_at', 'updated_at'
        ]
    
    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username or f"User {obj.user.telegram_id}"
    
    def get_location_display(self, obj):
        return obj.get_location_display()
    
    def get_price_formatted(self, obj):
        return f"{obj.price:,.0f} сум"
    
    def get_is_favorited(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'user_id'):
            try:
                user = TelegramUser.objects.get(telegram_id=request.user_id)
                return Favorite.objects.filter(user=user, property=obj).exists()
            except TelegramUser.DoesNotExist:
                pass
        return False
    
    def get_days_ago(self, obj):
        delta = timezone.now() - obj.created_at
        days = delta.days
        if days == 0:
            hours = delta.seconds // 3600
            if hours == 0:
                minutes = delta.seconds // 60
                return f"{minutes} мин назад" if minutes > 0 else "только что"
            return f"{hours} ч назад"
        elif days == 1:
            return "вчера"
        elif days < 7:
            return f"{days} дн назад"
        elif days < 30:
            weeks = days // 7
            return f"{weeks} нед назад"
        else:
            months = days // 30
            return f"{months} мес назад"

class PropertyDetailSerializer(serializers.ModelSerializer):
    """Serializer for property detail view (full data)"""
    user = TelegramUserSerializer(read_only=True)
    location_display = serializers.SerializerMethodField()
    price_formatted = serializers.SerializerMethodField()
    property_type_display = serializers.CharField(source='get_property_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    condition_display = serializers.CharField(source='get_condition_display', read_only=True)
    images = PropertyImageSerializer(many=True, read_only=True)
    is_favorited = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    region_info = serializers.SerializerMethodField()
    district_info = serializers.SerializerMethodField()
    similar_properties = serializers.SerializerMethodField()
    
    class Meta:
        model = Property
        fields = [
            'id', 'title', 'description', 'property_type', 'property_type_display',
            'status', 'status_display', 'condition', 'condition_display',
            'region', 'district', 'address', 'full_address', 'location_display',
            'region_info', 'district_info', 'price', 'price_formatted', 'area', 
            'rooms', 'contact_info', 'photo_file_ids', 'images', 'is_premium',
            'views_count', 'favorites_count', 'user', 'is_favorited', 'is_owner',
            'similar_properties', 'created_at', 'updated_at', 'published_at'
        ]
    
    def get_location_display(self, obj):
        return obj.get_location_display()
    
    def get_price_formatted(self, obj):
        return f"{obj.price:,.0f} сум"
    
    def get_is_favorited(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'user_id'):
            try:
                user = TelegramUser.objects.get(telegram_id=request.user_id)
                return Favorite.objects.filter(user=user, property=obj).exists()
            except TelegramUser.DoesNotExist:
                pass
        return False
    
    def get_is_owner(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'user_id'):
            try:
                user = TelegramUser.objects.get(telegram_id=request.user_id)
                return obj.user == user
            except TelegramUser.DoesNotExist:
                pass
        return False
    
    def get_region_info(self, obj):
        if obj.region:
            try:
                region = Region.objects.get(key=obj.region)
                return RegionSerializer(region).data
            except Region.DoesNotExist:
                pass
        return None
    
    def get_district_info(self, obj):
        if obj.region and obj.district:
            try:
                region = Region.objects.get(key=obj.region)
                district = District.objects.get(region=region, key=obj.district)
                return DistrictSerializer(district).data
            except (Region.DoesNotExist, District.DoesNotExist):
                pass
        return None
    
    def get_similar_properties(self, obj):
        # Get similar properties based on type, region, and price range
        price_min = obj.price * 0.8
        price_max = obj.price * 1.2
        
        similar = Property.objects.filter(
            property_type=obj.property_type,
            region=obj.region,
            price__gte=price_min,
            price__lte=price_max,
            is_approved=True,
            is_active=True
        ).exclude(id=obj.id).order_by('-is_premium', '-created_at')[:3]
        
        return PropertyListSerializer(similar, many=True, context=self.context).data

class PropertySerializer(serializers.ModelSerializer):
    """Serializer for property create/update operations"""
    user_id = serializers.IntegerField(write_only=True, required=False)
    location_display = serializers.CharField(source='get_location_display', read_only=True)
    property_type_display = serializers.CharField(source='get_property_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = Property
        fields = [
            'id', 'title', 'description', 'property_type', 'property_type_display',
            'status', 'status_display', 'condition', 'region', 'district',
            'address', 'full_address', 'location_display', 'price', 'area', 
            'rooms', 'contact_info', 'photo_file_ids', 'is_premium',
            'is_approved', 'is_active', 'approval_status', 'views_count',
            'favorites_count', 'user_id', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'views_count', 'favorites_count', 'created_at', 'updated_at',
            'location_display', 'property_type_display', 'status_display'
        ]
    
    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than 0")
        return value
    
    def validate_area(self, value):
        if value <= 0:
            raise serializers.ValidationError("Area must be greater than 0")
        return value
    
    def validate_rooms(self, value):
        if value < 0:
            raise serializers.ValidationError("Number of rooms cannot be negative")
        return value
    
    def validate_photo_file_ids(self, value):
        if value and not isinstance(value, list):
            raise serializers.ValidationError("Photo file IDs must be a list")
        if value and len(value) > 10:
            raise serializers.ValidationError("Maximum 10 photos allowed")
        return value
    
    def validate(self, data):
        # Validate region and district combination
        region_key = data.get('region')
        district_key = data.get('district')
        
        if region_key and district_key:
            try:
                region = Region.objects.get(key=region_key, is_active=True)
                District.objects.get(region=region, key=district_key, is_active=True)
            except (Region.DoesNotExist, District.DoesNotExist):
                raise serializers.ValidationError("Invalid region/district combination")
        
        return data

class FavoriteSerializer(serializers.ModelSerializer):
    property = PropertyListSerializer(read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    
    class Meta:
        model = Favorite
        fields = ['id', 'property', 'user_name', 'created_at']

class UserActivitySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    property_title = serializers.CharField(source='property.get_title', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    
    class Meta:
        model = UserActivity
        fields = [
            'id', 'action', 'action_display', 'user_name', 'property_title',
            'details', 'ip_address', 'created_at'
        ]
        read_only_fields = ['created_at']

class SearchQuerySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    search_type_display = serializers.CharField(source='get_search_type_display', read_only=True)
    
    class Meta:
        model = SearchQuery
        fields = [
            'id', 'query', 'search_type', 'search_type_display', 'user_name',
            'filters_used', 'results_count', 'created_at'
        ]
        read_only_fields = ['created_at']

# Statistics serializers
class PropertyStatsSerializer(serializers.Serializer):
    total_properties = serializers.IntegerField()
    active_properties = serializers.IntegerField()
    premium_properties = serializers.IntegerField()
    properties_today = serializers.IntegerField()
    properties_this_week = serializers.IntegerField()
    properties_this_month = serializers.IntegerField()
    properties_by_type = serializers.ListField()
    properties_by_status = serializers.ListField()
    properties_by_region = serializers.ListField()
    price_statistics = serializers.DictField()
    recent_properties = PropertyListSerializer(many=True)
    popular_searches = serializers.ListField()
    premium_percentage = serializers.FloatField()
    active_percentage = serializers.FloatField()

class UserStatsSerializer(serializers.Serializer):
    user_info = TelegramUserSerializer()
    properties = serializers.DictField()
    engagement = serializers.DictField()
    recent_activities = UserActivitySerializer(many=True)