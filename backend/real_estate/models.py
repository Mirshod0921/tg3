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
        verbose_name = "Telegram User"
        verbose_name_plural = "Telegram Users"
        ordering = ['-created_at']

class Region(models.Model):
    name_uz = models.CharField(max_length=100, verbose_name="Name (Uzbek)")
    name_ru = models.CharField(max_length=100, verbose_name="Name (Russian)")
    name_en = models.CharField(max_length=100, verbose_name="Name (English)")
    key = models.CharField(max_length=50, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    
    def __str__(self):
        return self.name_uz
    
    def get_name(self, language='uz'):
        return getattr(self, f'name_{language}', self.name_uz)
    
    class Meta:
        verbose_name = "Region"
        verbose_name_plural = "Regions"
        ordering = ['order', 'name_uz']

class District(models.Model):
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='districts')
    name_uz = models.CharField(max_length=100, verbose_name="Name (Uzbek)")
    name_ru = models.CharField(max_length=100, verbose_name="Name (Russian)")
    name_en = models.CharField(max_length=100, verbose_name="Name (English)")
    key = models.CharField(max_length=50, db_index=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    
    def __str__(self):
        return f"{self.region.name_uz} - {self.name_uz}"
    
    def get_name(self, language='uz'):
        return getattr(self, f'name_{language}', self.name_uz)
    
    class Meta:
        verbose_name = "District"
        verbose_name_plural = "Districts"
        unique_together = ['region', 'key']
        ordering = ['region__order', 'order', 'name_uz']

class Property(models.Model):
    PROPERTY_TYPES = [
        ('apartment', 'Квартира'),
        ('house', 'Дом'),
        ('commercial', 'Коммерческая'),
        ('land', 'Земля'),
    ]
    
    CONDITION_CHOICES = [
        ('new', 'Новое'),
        ('good', 'Хорошее'),
        ('repair_needed', 'Требует ремонта'),
    ]
    
    STATUS_CHOICES = [
        ('sale', 'Продажа'),
        ('rent', 'Аренда'),
    ]
    
    APPROVAL_STATUS_CHOICES = [
        ('pending', 'На рассмотрении'),
        ('approved', 'Одобрено'),
        ('rejected', 'Отклонено'),
    ]
    
    # Basic information
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='properties')
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField()
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPES)
    
    # Location
    region = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    district = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    address = models.CharField(max_length=300)
    full_address = models.CharField(max_length=500, blank=True)
    
    # Property details
    price = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(0)])
    area = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)], help_text="Area in m²")
    rooms = models.PositiveIntegerField(validators=[MinValueValidator(0), MaxValueValidator(50)], default=0)
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    contact_info = models.CharField(max_length=200)
    
    # Media
    photo_file_ids = models.JSONField(default=list, blank=True, help_text="Telegram file IDs")
    
    # Status and visibility
    is_premium = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    approval_status = models.CharField(max_length=20, choices=APPROVAL_STATUS_CHOICES, default='pending')
    admin_notes = models.TextField(blank=True, help_text="Internal admin notes")
    
    # Statistics
    views_count = models.PositiveIntegerField(default=0)
    favorites_count = models.PositiveIntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    
    # Channel posting
    channel_message_id = models.BigIntegerField(null=True, blank=True)
    posted_to_channel = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.get_title()} - {self.price:,.0f} сум"
    
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
                return f"{district.get_name(language)}, {region.get_name(language)}"
        except (Region.DoesNotExist, District.DoesNotExist):
            pass
        
        return self.full_address or self.address
    
    def increment_views(self):
        """Increment view count"""
        self.views_count = models.F('views_count') + 1
        self.save(update_fields=['views_count'])
    
    def get_absolute_url(self):
        return reverse('property-detail', kwargs={'pk': self.pk})
    
    def get_property_type_display_ru(self):
        type_mapping = {
            'apartment': 'Квартира',
            'house': 'Дом', 
            'commercial': 'Коммерческая',
            'land': 'Земля'
        }
        return type_mapping.get(self.property_type, self.property_type)
    
    def get_status_display_ru(self):
        status_mapping = {
            'sale': 'Продажа',
            'rent': 'Аренда'
        }
        return status_mapping.get(self.status, self.status)
    
    class Meta:
        verbose_name = "Property"
        verbose_name_plural = "Properties"
        ordering = ['-is_premium', '-created_at']
        indexes = [
            models.Index(fields=['is_approved', 'is_active']),
            models.Index(fields=['property_type', 'status']),
            models.Index(fields=['region', 'district']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['price']),
        ]

class Favorite(models.Model):
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='favorites')
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user} - {self.property.get_title()}"
    
    class Meta:
        unique_together = ['user', 'property']
        verbose_name = "Favorite"
        verbose_name_plural = "Favorites"
        ordering = ['-created_at']

class UserActivity(models.Model):
    ACTION_TYPES = [
        ('start', 'Запуск бота'),
        ('post_listing', 'Размещение объявления'),
        ('view_listing', 'Просмотр объявления'),
        ('search', 'Поиск'),
        ('favorite_add', 'Добавление в избранное'),
        ('favorite_remove', 'Удаление из избранного'),
        ('contact', 'Обращение к продавцу'),
        ('language_change', 'Смена языка'),
        ('premium_purchase', 'Покупка премиум'),
    ]
    
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='activities')
    action = models.CharField(max_length=20, choices=ACTION_TYPES)
    details = models.JSONField(blank=True, null=True)
    property = models.ForeignKey(Property, on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    def __str__(self):
        return f"{self.user} - {self.get_action_display()} ({self.created_at})"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "User Activity"
        verbose_name_plural = "User Activities"
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]

class PropertyImage(models.Model):
    """Model to store property images with metadata"""
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='images')
    telegram_file_id = models.CharField(max_length=200, unique=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_main = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Image for {self.property.get_title()}"
    
    class Meta:
        ordering = ['order', 'uploaded_at']
        verbose_name = "Property Image"
        verbose_name_plural = "Property Images"

class SearchQuery(models.Model):
    """Track search queries for analytics"""
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='searches', null=True, blank=True)
    query = models.CharField(max_length=500)
    search_type = models.CharField(max_length=50, choices=[
        ('keyword', 'Keyword Search'),
        ('location', 'Location Search'),
        ('filters', 'Advanced Filters'),
    ])
    filters_used = models.JSONField(default=dict, blank=True)
    results_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Search: {self.query} ({self.results_count} results)"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Search Query"
        verbose_name_plural = "Search Queries"

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