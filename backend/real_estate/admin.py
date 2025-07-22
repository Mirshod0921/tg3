from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count, Sum, Q
from django.urls import reverse
from django.utils import timezone
from django.http import HttpResponseRedirect
from django.contrib import messages
from datetime import datetime, timedelta
import json

from .models import (
    TelegramUser, Region, District, Property, Favorite, 
    UserActivity, PropertyImage, SearchQuery
)

# Custom admin site configuration
admin.site.site_header = "Real Estate Bot Administration"
admin.site.site_title = "Real Estate Bot Admin"
admin.site.index_title = "Dashboard"

class PropertyImageInline(admin.TabularInline):
    model = PropertyImage
    extra = 0
    readonly_fields = ['telegram_file_id', 'file_size', 'width', 'height', 'uploaded_at']
    fields = ['telegram_file_id', 'order', 'is_main', 'file_size', 'uploaded_at']

@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = [
        'telegram_id', 'get_full_name', 'username', 'language', 
        'is_blocked', 'is_premium', 'balance', 'properties_count', 
        'favorites_count', 'created_at'
    ]
    list_filter = [
        'language', 'is_blocked', 'is_premium', 
        ('created_at', admin.DateFieldListFilter),
        ('premium_expires_at', admin.DateFieldListFilter),
    ]
    search_fields = ['telegram_id', 'username', 'first_name', 'last_name']
    list_editable = ['is_blocked', 'language', 'balance']
    readonly_fields = ['telegram_id', 'created_at', 'updated_at', 'properties_count', 'favorites_count']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('telegram_id', 'username', 'first_name', 'last_name', 'language')
        }),
        ('Status', {
            'fields': ('is_blocked', 'is_premium', 'premium_expires_at', 'balance')
        }),
        ('Statistics', {
            'fields': ('properties_count', 'favorites_count'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['block_users', 'unblock_users', 'make_premium', 'remove_premium']
    
    def get_full_name(self, obj):
        return obj.get_full_name() or '(No name)'
    get_full_name.short_description = "Full Name"
    
    def properties_count(self, obj):
        count = obj.properties.count()
        if count > 0:
            url = reverse('admin:real_estate_property_changelist') + f'?user__id__exact={obj.id}'
            return format_html('<a href="{}">{} properties</a>', url, count)
        return '0'
    properties_count.short_description = "Properties"
    
    def favorites_count(self, obj):
        count = obj.favorites.count()
        if count > 0:
            url = reverse('admin:real_estate_favorite_changelist') + f'?user__id__exact={obj.id}'
            return format_html('<a href="{}">{} favorites</a>', url, count)
        return '0'
    favorites_count.short_description = "Favorites"
    
    def block_users(self, request, queryset):
        updated = queryset.update(is_blocked=True)
        messages.success(request, f'{updated} users blocked.')
    block_users.short_description = "Block selected users"
    
    def unblock_users(self, request, queryset):
        updated = queryset.update(is_blocked=False)
        messages.success(request, f'{updated} users unblocked.')
    unblock_users.short_description = "Unblock selected users"
    
    def make_premium(self, request, queryset):
        expire_date = timezone.now() + timedelta(days=30)
        updated = queryset.update(is_premium=True, premium_expires_at=expire_date)
        messages.success(request, f'{updated} users made premium for 30 days.')
    make_premium.short_description = "Make premium (30 days)"
    
    def remove_premium(self, request, queryset):
        updated = queryset.update(is_premium=False, premium_expires_at=None)
        messages.success(request, f'{updated} users premium status removed.')
    remove_premium.short_description = "Remove premium status"

@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ['name_uz', 'name_ru', 'name_en', 'key', 'is_active', 'order', 'districts_count', 'properties_count']
    list_editable = ['is_active', 'order']
    search_fields = ['name_uz', 'name_ru', 'name_en', 'key']
    list_filter = ['is_active']
    ordering = ['order', 'name_uz']
    
    def districts_count(self, obj):
        count = obj.districts.count()
        if count > 0:
            url = reverse('admin:real_estate_district_changelist') + f'?region__id__exact={obj.id}'
            return format_html('<a href="{}">{} districts</a>', url, count)
        return '0'
    districts_count.short_description = "Districts"
    
    def properties_count(self, obj):
        count = Property.objects.filter(region=obj.key).count()
        if count > 0:
            url = reverse('admin:real_estate_property_changelist') + f'?region__exact={obj.key}'
            return format_html('<a href="{}">{} properties</a>', url, count)
        return '0'
    properties_count.short_description = "Properties"

@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ['name_uz', 'region', 'name_ru', 'name_en', 'key', 'is_active', 'order', 'properties_count']
    list_filter = ['region', 'is_active']
    list_editable = ['is_active', 'order']
    search_fields = ['name_uz', 'name_ru', 'name_en', 'key', 'region__name_uz']
    ordering = ['region__order', 'order', 'name_uz']
    
    def properties_count(self, obj):
        count = Property.objects.filter(region=obj.region.key, district=obj.key).count()
        if count > 0:
            url = reverse('admin:real_estate_property_changelist') + f'?region__exact={obj.region.key}&district__exact={obj.key}'
            return format_html('<a href="{}">{} properties</a>', url, count)
        return '0'
    properties_count.short_description = "Properties"

@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'get_title_short', 'user_link', 'property_type', 'status',
        'get_location', 'price_formatted', 'area', 'approval_status_colored',
        'is_premium', 'views_count', 'favorites_count', 'created_at'
    ]
    list_filter = [
        'property_type', 'status', 'condition', 'approval_status',
        'is_premium', 'is_approved', 'is_active',
        ('created_at', admin.DateFieldListFilter),
        ('published_at', admin.DateFieldListFilter),
        'region', 'posted_to_channel'
    ]
    search_fields = [
        'title', 'description', 'address', 'full_address', 
        'user__first_name', 'user__last_name', 'user__username',
        'contact_info'
    ]
    list_editable = ['is_premium']  # Removed 'approval_status' since it's not in list_display
    readonly_fields = [
        'views_count', 'favorites_count', 'created_at', 'updated_at',
        'published_at', 'channel_message_id', 'get_photos_preview'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'title', 'description', 'property_type', 'status')
        }),
        ('Location', {
            'fields': ('region', 'district', 'address', 'full_address')
        }),
        ('Property Details', {
            'fields': ('price', 'area', 'rooms', 'condition', 'contact_info')
        }),
        ('Media', {
            'fields': ('photo_file_ids', 'get_photos_preview'),
            'classes': ('collapse',)
        }),
        ('Status & Approval', {
            'fields': ('approval_status', 'is_premium', 'is_approved', 'is_active', 'admin_notes')
        }),
        ('Channel Integration', {
            'fields': ('posted_to_channel', 'channel_message_id'),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('views_count', 'favorites_count'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'published_at', 'expires_at'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [PropertyImageInline]
    actions = [
        'approve_properties', 'reject_properties', 'make_premium', 
        'make_regular', 'activate_properties', 'deactivate_properties'
    ]
    
    def get_title_short(self, obj):
        title = obj.get_title()
        if len(title) > 50:
            return title[:50] + '...'
        return title
    get_title_short.short_description = "Title"
    
    def user_link(self, obj):
        url = reverse('admin:real_estate_telegramuser_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username or f'ID: {obj.user.telegram_id}')
    user_link.short_description = "User"
    
    def get_location(self, obj):
        return obj.get_location_display() or '-'
    get_location.short_description = "Location"
    
    def price_formatted(self, obj):
        if obj.price is not None:
            try:
                # Ensure price is a number
                price = float(obj.price)
                return format_html('<strong>{:,.0f} сум</strong>', price)
            except (ValueError, TypeError):
                return format_html('<strong>{} сум</strong>', obj.price)
        return '-'
    price_formatted.short_description = "Price"
    
    def approval_status_colored(self, obj):
        colors = {
            'pending': 'orange',
            'approved': 'green',
            'rejected': 'red'
        }
        color = colors.get(obj.approval_status, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_approval_status_display()
        )
    approval_status_colored.short_description = "Status"
    
    def get_photos_preview(self, obj):
        if not obj.photo_file_ids:
            return "No photos"
        
        count = len(obj.photo_file_ids) if isinstance(obj.photo_file_ids, list) else 0
        return format_html(
            '<span title="Photo IDs: {}"><strong>{} photos</strong></span>',
            ', '.join(obj.photo_file_ids[:3]) + ('...' if count > 3 else ''),
            count
        )
    get_photos_preview.short_description = "Photos"
    
    def approve_properties(self, request, queryset):
        updated = queryset.update(approval_status='approved', is_approved=True, published_at=timezone.now())
        messages.success(request, f'{updated} properties approved.')
    approve_properties.short_description = "Approve selected properties"
    
    def reject_properties(self, request, queryset):
        updated = queryset.update(approval_status='rejected', is_approved=False)
        messages.success(request, f'{updated} properties rejected.')
    reject_properties.short_description = "Reject selected properties"
    
    def make_premium(self, request, queryset):
        updated = queryset.update(is_premium=True)
        messages.success(request, f'{updated} properties made premium.')
    make_premium.short_description = "Make premium"
    
    def make_regular(self, request, queryset):
        updated = queryset.update(is_premium=False)
        messages.success(request, f'{updated} properties made regular.')
    make_regular.short_description = "Make regular"
    
    def activate_properties(self, request, queryset):
        updated = queryset.update(is_active=True)
        messages.success(request, f'{updated} properties activated.')
    activate_properties.short_description = "Activate properties"
    
    def deactivate_properties(self, request, queryset):
        updated = queryset.update(is_active=False)
        messages.success(request, f'{updated} properties deactivated.')
    deactivate_properties.short_description = "Deactivate properties"

@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ['user_link', 'property_link', 'created_at']
    list_filter = [('created_at', admin.DateFieldListFilter)]
    search_fields = [
        'user__first_name', 'user__last_name', 'user__username',
        'property__title', 'property__description'
    ]
    readonly_fields = ['created_at']
    
    def user_link(self, obj):
        url = reverse('admin:real_estate_telegramuser_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username or f'ID: {obj.user.telegram_id}')
    user_link.short_description = "User"
    
    def property_link(self, obj):
        url = reverse('admin:real_estate_property_change', args=[obj.property.id])
        return format_html('<a href="{}">{}</a>', url, obj.property.get_title())
    property_link.short_description = "Property"

@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ['user_link', 'action', 'property_link', 'created_at']
    list_filter = [
        'action', 
        ('created_at', admin.DateFieldListFilter),
    ]
    search_fields = [
        'user__first_name', 'user__last_name', 'user__username',
        'property__title'
    ]
    readonly_fields = ['created_at', 'details_formatted']
    
    fieldsets = (
        ('Activity Info', {
            'fields': ('user', 'action', 'property')
        }),
        ('Technical Details', {
            'fields': ('details_formatted', 'ip_address', 'user_agent'),
            'classes': ('collapse',)
        }),
        ('Timestamp', {
            'fields': ('created_at',)
        }),
    )
    
    def user_link(self, obj):
        url = reverse('admin:real_estate_telegramuser_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username or f'ID: {obj.user.telegram_id}')
    user_link.short_description = "User"
    
    def property_link(self, obj):
        if obj.property:
            url = reverse('admin:real_estate_property_change', args=[obj.property.id])
            return format_html('<a href="{}">{}</a>', url, obj.property.get_title())
        return '-'
    property_link.short_description = "Property"
    
    def details_formatted(self, obj):
        if obj.details:
            return format_html('<pre>{}</pre>', json.dumps(obj.details, indent=2, ensure_ascii=False))
        return 'No details'
    details_formatted.short_description = "Details"

@admin.register(SearchQuery)
class SearchQueryAdmin(admin.ModelAdmin):
    list_display = ['query', 'search_type', 'user_link', 'results_count', 'created_at']
    list_filter = [
        'search_type',
        ('created_at', admin.DateFieldListFilter),
        'results_count'
    ]
    search_fields = ['query', 'user__username', 'user__first_name']
    readonly_fields = ['created_at', 'filters_formatted']
    
    def user_link(self, obj):
        if obj.user:
            url = reverse('admin:real_estate_telegramuser_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username or f'ID: {obj.user.telegram_id}')
        return 'Anonymous'
    user_link.short_description = "User"
    
    def filters_formatted(self, obj):
        if obj.filters_used:
            return format_html('<pre>{}</pre>', json.dumps(obj.filters_used, indent=2, ensure_ascii=False))
        return 'No filters'
    filters_formatted.short_description = "Filters Used"

# Custom dashboard views
class RealEstateAdminSite(admin.AdminSite):
    site_header = "Real Estate Bot Administration"
    site_title = "Real Estate Bot Admin"
    index_title = "Dashboard"
    
    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
        
        # Get statistics for dashboard
        now = timezone.now()
        today = now.date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        stats = {
            'total_users': TelegramUser.objects.count(),
            'active_users_week': TelegramUser.objects.filter(
                activities__created_at__gte=week_ago
            ).distinct().count(),
            'total_properties': Property.objects.count(),
            'pending_properties': Property.objects.filter(approval_status='pending').count(),
            'approved_properties': Property.objects.filter(approval_status='approved').count(),
            'premium_properties': Property.objects.filter(is_premium=True).count(),
            'total_favorites': Favorite.objects.count(),
            'properties_this_month': Property.objects.filter(created_at__gte=month_ago).count(),
            'users_this_month': TelegramUser.objects.filter(created_at__gte=month_ago).count(),
        }
        
        # Recent activities
        recent_activities = UserActivity.objects.select_related('user', 'property')[:10]
        
        # Top regions by property count
        region_stats = []
        for region in Region.objects.all():
            count = Property.objects.filter(region=region.key, is_approved=True).count()
            if count > 0:
                region_stats.append({
                    'name': region.name_uz,
                    'count': count
                })
        region_stats = sorted(region_stats, key=lambda x: x['count'], reverse=True)[:5]
        
        extra_context.update({
            'stats': stats,
            'recent_activities': recent_activities,
            'top_regions': region_stats,
        })
        
        return super().index(request, extra_context)

# Replace default admin site
admin_site = RealEstateAdminSite(name='admin')
admin_site._registry = admin.site._registry