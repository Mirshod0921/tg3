# backend/payments/admin.py (simplified)
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Payment, ClickTransaction, PaymeTransaction

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user_link', 'amount_display', 'payment_method', 
        'service_type', 'status_badge', 'created_at'
    ]
    list_filter = [
        'payment_method', 'service_type', 'status', 'created_at'
    ]
    search_fields = [
        'user__first_name', 'user__last_name', 'user__username',
        'transaction_id', 'external_id'
    ]
    readonly_fields = ['created_at', 'completed_at']
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('user', 'amount', 'payment_method', 'service_type', 'description')
        }),
        ('Status & Transaction', {
            'fields': ('status', 'transaction_id', 'external_id')
        }),
        ('Related Objects', {
            'fields': ('property',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_completed', 'mark_as_failed']
    
    def user_link(self, obj):
        try:
            url = reverse('admin:real_estate_telegramuser_change', args=[obj.user.pk])
            return format_html(
                '<a href="{}">{}</a>',
                url, obj.user.first_name or f"ID: {obj.user.telegram_id}"
            )
        except:
            return obj.user.first_name or f"ID: {obj.user.telegram_id}"
    user_link.short_description = "User"
    
    def amount_display(self, obj):
        return f"{obj.amount:,.2f} UZS"
    amount_display.short_description = "Amount"
    
    def status_badge(self, obj):
        color_map = {
            'completed': 'green',
            'pending': 'orange',
            'failed': 'red',
            'cancelled': 'gray'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color_map.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_badge.short_description = "Status"
    
    def mark_as_completed(self, request, queryset):
        updated = 0
        for payment in queryset.filter(status='pending'):
            payment.mark_completed()
            updated += 1
        self.message_user(request, f'{updated} payments marked as completed.')
    mark_as_completed.short_description = "Mark as completed"
    
    def mark_as_failed(self, request, queryset):
        updated = queryset.filter(status='pending').update(status='failed')
        self.message_user(request, f'{updated} payments marked as failed.')
    mark_as_failed.short_description = "Mark as failed"

@admin.register(ClickTransaction)
class ClickTransactionAdmin(admin.ModelAdmin):
    list_display = ['payment', 'click_trans_id', 'amount', 'action', 'error', 'created_at']
    list_filter = ['action', 'error', 'created_at']
    search_fields = ['click_trans_id', 'merchant_trans_id']
    readonly_fields = ['created_at']

@admin.register(PaymeTransaction)
class PaymeTransactionAdmin(admin.ModelAdmin):
    list_display = ['payment', 'payme_id', 'amount', 'state', 'create_time']
    list_filter = ['state']
    search_fields = ['payme_id']