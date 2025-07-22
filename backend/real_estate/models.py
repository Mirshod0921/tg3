# backend/real_estate/models.py - Updated based on actual user flow
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.urls import reverse
import json

class TelegramUser(models.Model):
    LANGUAGE_CHOICES = [
        ('uz', "O'zbekcha"),
        ('ru', 'Русский'),
        ('en', 'English'),
    ]
    
    telegram_id = models.BigIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=100, blank=True, null=True)
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default='uz')
    is_blocked = models.BooleanField(default=False)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_premium = models.BooleanField(default=False)
    premium_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        name = f"{self.first_name or ''} {self.last_name or ''}".strip()
        username_part = f"@{self.username}" if self.username else ""
        return f"{name} ({username_part})" if name else str(self.telegram_id)
    
    def get_full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip()
    
    def is_premium_active(self):
        if not self.is_premium:
            return False
        if not self.premium_expires_at:
            return True
        return timezone.now() < self.premium_expires_at
    
    class Meta:
        verbose_name = "Telegram Foydalanuvchi"
        verbose_name_plural = "Telegram Foydalanuvchilar"
        ordering = ['-created_at']

class Region(models.Model):
    # Only Uzbek name needed for admin
    name_uz = models.CharField(max_length=100, verbose_name="Nomi")
    key = models.CharField(max_length=50, unique=True, db_index=True)
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib")
    
    def __str__(self):
        return self.name_uz
    
    class Meta:
        verbose_name = "Viloyat"
        verbose_name_plural = "Viloyatlar"
        ordering = ['order', 'name_uz']

class District(models.Model):
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='districts', verbose_name="Viloyat")
    # Only Uzbek name needed for admin
    name_uz = models.CharField(max_length=100, verbose_name="Nomi")
    key = models.CharField(max_length=50, db_index=True)
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib")
    
    def __str__(self):
        return f"{self.region.name_uz} - {self.name_uz}"
    
    class Meta:
        verbose_name = "Tuman"
        verbose_name_plural = "Tumanlar"
        unique_together = ['region', 'key']
        ordering = ['region__order', 'order', 'name_uz']

class Property(models.Model):
    # Based on actual user input flow from main.py
    PROPERTY_TYPES = [
        ('apartment', 'Kvartira'),
        ('house', 'Uy'),
        ('commercial', 'Tijorat'),
        ('land', 'Yer'),
    ]
    
    STATUS_CHOICES = [
        ('sale', 'Sotiladi'),
        ('rent', 'Ijara'),
    ]
    
    APPROVAL_STATUS_CHOICES = [
        ('pending', 'Kutilmoqda'),
        ('approved', 'Tasdiqlangan'),
        ('rejected', 'Rad etilgan'),
    ]
    
    # User and basic info
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='properties', verbose_name="Foydalanuvchi")
    title = models.CharField(max_length=200, blank=True, verbose_name="Sarlavha")
    description = models.TextField(verbose_name="Tavsif")
    
    # User selects these in bot
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPES, verbose_name="Mulk turi")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, verbose_name="Maqsad")
    
    # Location (user selects region and district)
    region = models.CharField(max_length=50, blank=True, null=True, db_index=True, verbose_name="Viloyat")
    district = models.CharField(max_length=50, blank=True, null=True, db_index=True, verbose_name="Tuman")
    address = models.CharField(max_length=300, verbose_name="Manzil")
    full_address = models.CharField(max_length=500, blank=True, verbose_name="To'liq manzil")
    
    # User enters these required fields
    price = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(0)], verbose_name="Narx")
    area = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)], 
                              help_text="m² da maydon", verbose_name="Maydon")
    contact_info = models.CharField(max_length=200, verbose_name="Aloqa ma'lumotlari")
    
    # Optional fields (removed rooms, condition as they're not consistently used)
    rooms = models.PositiveIntegerField(validators=[MinValueValidator(0), MaxValueValidator(50)], default=0, verbose_name="Xonalar soni")
    condition = models.CharField(max_length=20, blank=True, verbose_name="Holati")
    
    # Media
    photo_file_ids = models.JSONField(default=list, blank=True, help_text="Telegram fayl IDlari", verbose_name="Rasm ID lari")
    
    # Status and visibility
    is_premium = models.BooleanField(default=False, verbose_name="Premium")
    is_approved = models.BooleanField(default=False, db_index=True, verbose_name="Tasdiqlangan")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Faol")
    approval_status = models.CharField(max_length=20, choices=APPROVAL_STATUS_CHOICES, default='pending', verbose_name="Tasdiqlash holati")
    
    # Makler status (stored in admin_notes as per main.py)
    admin_notes = models.TextField(blank=True, help_text="Makler holati: 'makler' yoki 'maklersiz'", verbose_name="Admin eslatmalari")
    
    # Statistics
    views_count = models.PositiveIntegerField(default=0, verbose_name="Ko'rishlar soni")
    favorites_count = models.PositiveIntegerField(default=0, verbose_name="Sevimlilar soni")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Yaratilgan vaqt")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Yangilangan vaqt")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Muddati tugaydi")
    published_at = models.DateTimeField(null=True, blank=True, verbose_name="Nashr etilgan vaqt")
    
    # Channel posting
    channel_message_id = models.BigIntegerField(null=True, blank=True, verbose_name="Kanal xabar ID")
    posted_to_channel = models.BooleanField(default=False, verbose_name="Kanalga joylangan")
    
    def __str__(self):
        return f"{self.get_title()} - {self.price:,.0f} so'm"
    
    def get_title(self):
        if self.title:
            return self.title
        # Generate title from description (first 50 chars)
        return self.description[:50] + ('...' if len(self.description) > 50 else '')
    
    def save(self, *args, **kwargs):
        # Auto-generate title if not provided
        if not self.title:
            self.title = self.get_title()
        
        # Set published_at when approved
        if self.is_approved and not self.published_at:
            self.published_at = timezone.now()
        
        # Update favorites count
        if self.pk:
            self.favorites_count = self.favorited_by.count()
        
        super().save(*args, **kwargs)
    
    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False
    
    def get_first_photo_id(self):
        """Get first photo file_id for preview"""
        if self.photo_file_ids and isinstance(self.photo_file_ids, list):
            return self.photo_file_ids[0] if self.photo_file_ids else None
        return None
    
    def get_location_display(self, language='uz'):
        """Get human-readable location"""
        try:
            if self.region and self.district:
                region = Region.objects.get(key=self.region)
                district = District.objects.get(region=region, key=self.district)
                return f"{district.name_uz}, {region.name_uz}"
        except (Region.DoesNotExist, District.DoesNotExist):
            pass
        
        return self.full_address or self.address
    
    def increment_views(self):
        """Increment view count"""
        self.views_count = models.F('views_count') + 1
        self.save(update_fields=['views_count'])
    
    def get_absolute_url(self):
        return reverse('property-detail', kwargs={'pk': self.pk})
    
    def get_makler_status_display(self):
        """Display makler status"""
        if self.admin_notes == 'makler':
            return 'Makler'
        elif self.admin_notes == 'maklersiz':
            return 'Maklersiz'
        return 'Noma\'lum'
    
    class Meta:
        verbose_name = "E'lon"
        verbose_name_plural = "E'lonlar"
        ordering = ['-is_premium', '-created_at']
        indexes = [
            models.Index(fields=['is_approved', 'is_active']),
            models.Index(fields=['property_type', 'status']),
            models.Index(fields=['region', 'district']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['price']),
            models.Index(fields=['admin_notes']),  # For makler filtering
        ]

class Favorite(models.Model):
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='favorites', verbose_name="Foydalanuvchi")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='favorited_by', verbose_name="E'lon")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan vaqt")
    
    def __str__(self):
        return f"{self.user} - {self.property.get_title()}"
    
    class Meta:
        unique_together = ['user', 'property']
        verbose_name = "Sevimli"
        verbose_name_plural = "Sevimlilar"
        ordering = ['-created_at']

class UserActivity(models.Model):
    ACTION_TYPES = [
        ('start', 'Botni ishga tushirish'),
        ('post_listing', 'E\'lon joylashtirish'),
        ('view_listing', 'E\'lonni ko\'rish'),
        ('search', 'Qidiruv'),
        ('favorite_add', 'Sevimlilar qo\'shish'),
        ('favorite_remove', 'Sevimlidan o\'chirish'),
        ('contact', 'Sotuvchi bilan bog\'lanish'),
        ('language_change', 'Til o\'zgarishi'),
        ('premium_purchase', 'Premium xarid'),
    ]
    
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='activities', verbose_name="Foydalanuvchi")
    action = models.CharField(max_length=20, choices=ACTION_TYPES, verbose_name="Harakat")
    details = models.JSONField(blank=True, null=True, verbose_name="Tafsilotlar")
    property = models.ForeignKey(Property, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="E'lon")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP manzil")
    user_agent = models.TextField(blank=True, verbose_name="Brauzer ma'lumotlari")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Yaratilgan vaqt")
    
    def __str__(self):
        return f"{self.user} - {self.get_action_display()} ({self.created_at})"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Foydalanuvchi faoliyati"
        verbose_name_plural = "Foydalanuvchi faoliyatlari"
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]

class PropertyImage(models.Model):
    """Model to store property images with metadata"""
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='images', verbose_name="E'lon")
    telegram_file_id = models.CharField(max_length=200, unique=True, verbose_name="Telegram fayl ID")
    file_size = models.PositiveIntegerField(null=True, blank=True, verbose_name="Fayl hajmi")
    width = models.PositiveIntegerField(null=True, blank=True, verbose_name="Eni")
    height = models.PositiveIntegerField(null=True, blank=True, verbose_name="Bo'yi")
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib")
    is_main = models.BooleanField(default=False, verbose_name="Asosiy rasm")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="Yuklangan vaqt")
    
    def __str__(self):
        return f"{self.property.get_title()} uchun rasm"
    
    class Meta:
        ordering = ['order', 'uploaded_at']
        verbose_name = "E'lon rasmi"
        verbose_name_plural = "E'lon rasmlari"

class SearchQuery(models.Model):
    """Track search queries for analytics"""
    SEARCH_TYPES = [
        ('keyword', 'Kalit so\'z qidiruvi'),
        ('location', 'Joylashuv qidiruvi'),
        ('filters', 'Kengaytirilgan qidiruv'),
    ]
    
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='searches', 
                           null=True, blank=True, verbose_name="Foydalanuvchi")
    query = models.CharField(max_length=500, verbose_name="Qidiruv so'zi")
    search_type = models.CharField(max_length=50, choices=SEARCH_TYPES, verbose_name="Qidiruv turi")
    filters_used = models.JSONField(default=dict, blank=True, verbose_name="Ishlatilgan filtrlar")
    results_count = models.PositiveIntegerField(default=0, verbose_name="Natijalar soni")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan vaqt")
    
    def __str__(self):
        return f"Qidiruv: {self.query} ({self.results_count} ta natija)"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Qidiruv so'rovi"
        verbose_name_plural = "Qidiruv so'rovlari"

# Signal handlers to maintain data consistency
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

@receiver(post_save, sender=Favorite)
def update_favorites_count_add(sender, instance, created, **kwargs):
    if created:
        instance.property.favorites_count = instance.property.favorited_by.count()
        instance.property.save(update_fields=['favorites_count'])

@receiver(post_delete, sender=Favorite)
def update_favorites_count_remove(sender, instance, **kwargs):
    try:
        instance.property.favorites_count = instance.property.favorited_by.count()
        instance.property.save(update_fields=['favorites_count'])
    except Property.DoesNotExist:
        pass