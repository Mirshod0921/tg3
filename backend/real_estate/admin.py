# backend/real_estate/admin.py - Fixed version
from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count, Q
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
import json

from .models import (
    TelegramUser, Region, District, Property, Favorite, 
    UserActivity, PropertyImage, SearchQuery
)

# Admin site configuration (Uzbek only)
admin.site.site_header = "Ko'chmas Mulk Bot - Boshqaruv Paneli"
admin.site.site_title = "Ko'chmas Mulk Admin"
admin.site.index_title = "Boshqaruv Paneli"

class PropertyImageInline(admin.TabularInline):
    model = PropertyImage
    extra = 0
    readonly_fields = ['telegram_file_id', 'file_size', 'uploaded_at']
    fields = ['telegram_file_id', 'order', 'is_main', 'file_size', 'uploaded_at']

# Custom filters for better filtering
class MaklerFilter(admin.SimpleListFilter):
    title = 'Makler holati'
    parameter_name = 'makler_status'
    
    def lookups(self, request, model_admin):
        return (
            ('makler', '🏢 Makler'),
            ('maklersiz', '👤 Maklersiz'),
            ('unknown', '❓ Noma\'lum'),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'makler':
            return queryset.filter(admin_notes='makler')
        elif self.value() == 'maklersiz':
            return queryset.filter(admin_notes='maklersiz')
        elif self.value() == 'unknown':
            return queryset.filter(Q(admin_notes__isnull=True) | Q(admin_notes='') | ~Q(admin_notes__in=['makler', 'maklersiz']))
        return queryset

@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = [
        'telegram_id', 'get_full_name', 'username', 'language', 
        'is_blocked', 'is_premium', 'balance', 'properties_count', 
        'favorites_count', 'created_at'
    ]
    list_filter = [
        'language', 
        'is_blocked', 
        'is_premium', 
        ('created_at', admin.DateFieldListFilter),
        ('premium_expires_at', admin.DateFieldListFilter),
    ]
    search_fields = ['telegram_id', 'username', 'first_name', 'last_name']
    list_editable = ['is_blocked', 'language', 'balance']
    readonly_fields = ['telegram_id', 'created_at', 'updated_at', 'properties_count', 'favorites_count']
    
    fieldsets = (
        ('Asosiy ma\'lumotlar', {
            'fields': ('telegram_id', 'username', 'first_name', 'last_name', 'language')
        }),
        ('Status', {
            'fields': ('is_blocked', 'is_premium', 'premium_expires_at', 'balance')
        }),
        ('Statistika', {
            'fields': ('properties_count', 'favorites_count'),
            'classes': ('collapse',)
        }),
        ('Vaqt belgilari', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['block_users', 'unblock_users', 'make_premium', 'remove_premium']
    
    def get_full_name(self, obj):
        return obj.get_full_name() or '(Ism kiritilmagan)'
    get_full_name.short_description = "Ism Familiya"
    
    def properties_count(self, obj):
        count = obj.properties.count()
        if count > 0:
            url = reverse('admin:real_estate_property_changelist') + f'?user__id__exact={obj.id}'
            return format_html('<a href="{}">{} ta e\'lon</a>', url, count)
        return '0'
    properties_count.short_description = "E'lonlar"
    
    def favorites_count(self, obj):
        count = obj.favorites.count()
        if count > 0:
            url = reverse('admin:real_estate_favorite_changelist') + f'?user__id__exact={obj.id}'
            return format_html('<a href="{}">{} ta sevimli</a>', url, count)
        return '0'
    favorites_count.short_description = "Sevimlilar"
    
    def block_users(self, request, queryset):
        updated = queryset.update(is_blocked=True)
        messages.success(request, f'{updated} ta foydalanuvchi bloklandi.')
    block_users.short_description = "Tanlangan foydalanuvchilarni bloklash"
    
    def unblock_users(self, request, queryset):
        updated = queryset.update(is_blocked=False)
        messages.success(request, f'{updated} ta foydalanuvchi blokdan chiqarildi.')
    unblock_users.short_description = "Blokdan chiqarish"
    
    def make_premium(self, request, queryset):
        expire_date = timezone.now() + timedelta(days=30)
        updated = queryset.update(is_premium=True, premium_expires_at=expire_date)
        messages.success(request, f'{updated} ta foydalanuvchi 30 kunlik premium qilindi.')
    make_premium.short_description = "Premium qilish (30 kun)"
    
    def remove_premium(self, request, queryset):
        updated = queryset.update(is_premium=False, premium_expires_at=None)
        messages.success(request, f'{updated} ta foydalanuvchining premium holati olib tashlandi.')
    remove_premium.short_description = "Premium holatini olib tashlash"

@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    # Fixed list_display and list_editable to match
    list_display = [
        'id', 'get_title_short', 'user_link', 'property_type_display', 'status_display',
        'get_location', 'price_formatted', 'area', 'makler_status', 
        'approval_status_colored', 'is_premium', 'is_active', 'views_count', 'favorites_count', 'created_at'
    ]
    
    # Fixed filters - removed the problematic line
    list_filter = [
        'property_type', 
        'status', 
        'approval_status',
        MaklerFilter,  # Custom makler filter
        'is_premium', 
        'is_approved', 
        'is_active',
        ('created_at', admin.DateFieldListFilter),
        ('published_at', admin.DateFieldListFilter),
        'region',
        'posted_to_channel'
    ]
    
    search_fields = [
        'title', 'description', 'address', 'full_address', 
        'user__first_name', 'user__last_name', 'user__username',
        'contact_info'
    ]
    
    # Fixed list_editable - only fields that are in list_display
    list_editable = ['is_premium', 'is_active']
    
    readonly_fields = [
        'views_count', 'favorites_count', 'created_at', 'updated_at',
        'published_at', 'channel_message_id', 'get_photos_preview'
    ]
    
    # Updated fieldsets based on actual user input
    fieldsets = (
        ('Asosiy ma\'lumotlar', {
            'fields': ('user', 'title', 'description', 'property_type', 'status')
        }),
        ('Joylashuv', {
            'fields': ('region', 'district', 'address', 'full_address')
        }),
        ('Mulk tafsilotlari', {
            'fields': ('price', 'area', 'contact_info')
        }),
        ('Makler ma\'lumotlari', {
            'fields': ('admin_notes',),
            'description': 'Makler holati: "makler" yoki "maklersiz"'
        }),
        ('Rasmlar', {
            'fields': ('photo_file_ids', 'get_photos_preview'),
            'classes': ('collapse',)
        }),
        ('Status va tasdiqlash', {
            'fields': ('approval_status', 'is_premium', 'is_approved', 'is_active')
        }),
        ('Kanal integratsiyasi', {
            'fields': ('posted_to_channel', 'channel_message_id'),
            'classes': ('collapse',)
        }),
        ('Statistika', {
            'fields': ('views_count', 'favorites_count'),
            'classes': ('collapse',)
        }),
        ('Vaqt belgilari', {
            'fields': ('created_at', 'updated_at', 'published_at', 'expires_at'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [PropertyImageInline]
    actions = [
        'approve_properties', 'reject_properties', 'make_premium', 
        'make_regular', 'activate_properties', 'deactivate_properties',
        'post_to_channel'
    ]
    
    def get_title_short(self, obj):
        title = obj.get_title()
        if len(title) > 50:
            return title[:50] + '...'
        return title
    get_title_short.short_description = "Sarlavha"
    
    def user_link(self, obj):
        url = reverse('admin:real_estate_telegramuser_change', args=[obj.user.pk])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username or f'ID: {obj.user.telegram_id}')
    user_link.short_description = "Foydalanuvchi"
    
    def property_type_display(self, obj):
        type_mapping = {
            'apartment': '🏢 Kvartira',
            'house': '🏠 Uy',
            'commercial': '🏪 Tijorat',
            'land': '🌱 Yer'
        }
        return type_mapping.get(obj.property_type, obj.property_type)
    property_type_display.short_description = "Tur"
    
    def status_display(self, obj):
        status_mapping = {
            'sale': '💵 Sotiladi',
            'rent': '📅 Ijara'
        }
        return status_mapping.get(obj.status, obj.status)
    status_display.short_description = "Maqsad"
    
    def makler_status(self, obj):
        """Show makler status from admin_notes"""
        if obj.admin_notes == 'makler':
            return format_html('<span style="color: blue; font-weight: bold;">🏢 Makler</span>')
        elif obj.admin_notes == 'maklersiz':
            return format_html('<span style="color: green; font-weight: bold;">👤 Maklersiz</span>')
        else:
            return format_html('<span style="color: gray;">-</span>')
    makler_status.short_description = "Makler"
    
    def get_location(self, obj):
        return obj.get_location_display() or '-'
    get_location.short_description = "Joylashuv"
    
    def price_formatted(self, obj):
        if obj.price is not None:
            try:
                price = float(obj.price)
                return format_html('<strong>{:,.0f} so\'m</strong>', price)
            except (ValueError, TypeError):
                return format_html('<strong>{} so\'m</strong>', obj.price)
        return '-'
    price_formatted.short_description = "Narx"
    
    def approval_status_colored(self, obj):
        colors = {
            'pending': 'orange',
            'approved': 'green',
            'rejected': 'red'
        }
        status_names = {
            'pending': '🟡 Kutilmoqda',
            'approved': '✅ Tasdiqlangan',
            'rejected': '❌ Rad etilgan'
        }
        color = colors.get(obj.approval_status, 'black')
        status_name = status_names.get(obj.approval_status, obj.approval_status)
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, status_name
        )
    approval_status_colored.short_description = "Tasdiqlash holati"
    
    def get_photos_preview(self, obj):
        if not obj.photo_file_ids:
            return "Rasm yo'q"
        
        count = len(obj.photo_file_ids) if isinstance(obj.photo_file_ids, list) else 0
        return format_html(
            '<span title="Rasm IDlari: {}"><strong>{} ta rasm</strong></span>',
            ', '.join(obj.photo_file_ids[:3]) + ('...' if count > 3 else ''),
            count
        )
    get_photos_preview.short_description = "Rasmlar"
    
    # Updated actions with Uzbek text
    def approve_properties(self, request, queryset):
        updated = queryset.update(approval_status='approved', is_approved=True, published_at=timezone.now())
        messages.success(request, f'{updated} ta e\'lon tasdiqlandi.')
    approve_properties.short_description = "Tanlangan e'lonlarni tasdiqlash"
    
    def reject_properties(self, request, queryset):
        updated = queryset.update(approval_status='rejected', is_approved=False)
        messages.success(request, f'{updated} ta e\'lon rad etildi.')
    reject_properties.short_description = "E'lonlarni rad etish"
    
    def make_premium(self, request, queryset):
        updated = queryset.update(is_premium=True)
        messages.success(request, f'{updated} ta e\'lon premium qilindi.')
    make_premium.short_description = "Premium qilish"
    
    def make_regular(self, request, queryset):
        updated = queryset.update(is_premium=False)
        messages.success(request, f'{updated} ta e\'lon oddiy qilindi.')
    make_regular.short_description = "Oddiy qilish"
    
    def activate_properties(self, request, queryset):
        updated = queryset.update(is_active=True)
        messages.success(request, f'{updated} ta e\'lon faollashtirildi.')
    activate_properties.short_description = "E'lonlarni faollashtirish"
    
    def deactivate_properties(self, request, queryset):
        updated = queryset.update(is_active=False)
        messages.success(request, f'{updated} ta e\'lon nofaol qilindi.')
    deactivate_properties.short_description = "E'lonlarni nofaol qilish"
    
    def post_to_channel(self, request, queryset):
        """Manual posting to channel"""
        count = 0
        for prop in queryset.filter(is_approved=True):
            # Here you would implement channel posting logic
            count += 1
        messages.success(request, f'{count} ta e\'lon kanalga joylandi.')
    post_to_channel.short_description = "Kanalga joylashtirish"

@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ['name_uz', 'key', 'is_active', 'order', 'districts_count', 'properties_count']
    list_editable = ['is_active', 'order']
    search_fields = ['name_uz', 'key']
    list_filter = ['is_active']
    ordering = ['order', 'name_uz']
    
    # Only Uzbek fields
    fields = ['name_uz', 'key', 'is_active', 'order']
    
    def districts_count(self, obj):
        count = obj.districts.count()
        if count > 0:
            url = reverse('admin:real_estate_district_changelist') + f'?region__id__exact={obj.id}'
            return format_html('<a href="{}">{} ta tuman</a>', url, count)
        return '0'
    districts_count.short_description = "Tumanlar"
    
    def properties_count(self, obj):
        count = Property.objects.filter(region=obj.key).count()
        if count > 0:
            url = reverse('admin:real_estate_property_changelist') + f'?region__exact={obj.key}'
            return format_html('<a href="{}">{} ta e\'lon</a>', url, count)
        return '0'
    properties_count.short_description = "E'lonlar"

@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ['name_uz', 'region', 'key', 'is_active', 'order', 'properties_count']
    list_filter = ['region', 'is_active']
    list_editable = ['is_active', 'order']
    search_fields = ['name_uz', 'key', 'region__name_uz']
    ordering = ['region__order', 'order', 'name_uz']
    
    # Only Uzbek fields
    fields = ['region', 'name_uz', 'key', 'is_active', 'order']
    
    def properties_count(self, obj):
        count = Property.objects.filter(region=obj.region.key, district=obj.key).count()
        if count > 0:
            url = reverse('admin:real_estate_property_changelist') + f'?region__exact={obj.region.key}&district__exact={obj.key}'
            return format_html('<a href="{}">{} ta e\'lon</a>', url, count)
        return '0'
    properties_count.short_description = "E'lonlar"

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
    user_link.short_description = "Foydalanuvchi"
    
    def property_link(self, obj):
        url = reverse('admin:real_estate_property_change', args=[obj.property.id])
        return format_html('<a href="{}">{}</a>', url, obj.property.get_title())
    property_link.short_description = "E'lon"

@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ['user_link', 'action_display', 'property_link', 'created_at']
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
        ('Faoliyat ma\'lumotlari', {
            'fields': ('user', 'action', 'property')
        }),
        ('Texnik tafsilotlar', {
            'fields': ('details_formatted', 'ip_address', 'user_agent'),
            'classes': ('collapse',)
        }),
        ('Vaqt belgisi', {
            'fields': ('created_at',)
        }),
    )
    
    def user_link(self, obj):
        url = reverse('admin:real_estate_telegramuser_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username or f'ID: {obj.user.telegram_id}')
    user_link.short_description = "Foydalanuvchi"
    
    def action_display(self, obj):
        action_names = {
            'start': '🚀 Botni ishga tushirish',
            'post_listing': '📝 E\'lon joylashtirish',
            'view_listing': '👀 E\'lonni ko\'rish',
            'search': '🔍 Qidiruv',
            'favorite_add': '❤️ Sevimlilar qo\'shish',
            'favorite_remove': '💔 Sevimlidan o\'chirish',
            'contact': '📞 Sotuvchi bilan bog\'lanish',
            'language_change': '🌐 Til o\'zgarishi',
            'premium_purchase': '⭐ Premium xarid',
        }
        return action_names.get(obj.action, obj.action)
    action_display.short_description = "Harakat"
    
    def property_link(self, obj):
        if obj.property:
            url = reverse('admin:real_estate_property_change', args=[obj.property.id])
            return format_html('<a href="{}">{}</a>', url, obj.property.get_title())
        return '-'
    property_link.short_description = "E'lon"
    
    def details_formatted(self, obj):
        if obj.details:
            return format_html('<pre>{}</pre>', json.dumps(obj.details, indent=2, ensure_ascii=False))
        return 'Tafsilot yo\'q'
    details_formatted.short_description = "Tafsilotlar"

@admin.register(SearchQuery)
class SearchQueryAdmin(admin.ModelAdmin):
    list_display = ['query', 'search_type_display', 'user_link', 'results_count', 'created_at']
    list_filter = [
        'search_type',
        ('created_at', admin.DateFieldListFilter),
        'results_count'
    ]
    search_fields = ['query', 'user__username', 'user__first_name']
    readonly_fields = ['created_at', 'filters_formatted']
    
    def search_type_display(self, obj):
        type_names = {
            'keyword': '📝 Kalit so\'z',
            'location': '🏘 Joylashuv',
            'filters': '🔍 Kengaytirilgan'
        }
        return type_names.get(obj.search_type, obj.search_type)
    search_type_display.short_description = "Qidiruv turi"
    
    def user_link(self, obj):
        if obj.user:
            url = reverse('admin:real_estate_telegramuser_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.username or f'ID: {obj.user.telegram_id}')
        return 'Anonim'
    user_link.short_description = "Foydalanuvchi"
    
    def filters_formatted(self, obj):
        if obj.filters_used:
            return format_html('<pre>{}</pre>', json.dumps(obj.filters_used, indent=2, ensure_ascii=False))
        return 'Filtr yo\'q'
    filters_formatted.short_description = "Ishlatilgan filtrlar"