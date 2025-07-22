from django.db import models
from django.utils import timezone
from real_estate.models import TelegramUser, Property

class Payment(models.Model):
    PAYMENT_METHODS = [
        ('click', 'Click'),
        ('payme', 'Payme'),
    ]
    
    SERVICE_TYPES = [
        ('premium', 'Premium объявление'),
        ('ads', 'Реклама'),
        ('top_up', 'Пополнение баланса'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Ожидание'),
        ('completed', 'Завершено'),
        ('failed', 'Неудачно'),
        ('cancelled', 'Отменено'),
    ]
    
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS)
    service_type = models.CharField(max_length=20, choices=SERVICE_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    external_id = models.CharField(max_length=100, blank=True, null=True)
    property = models.ForeignKey(Property, on_delete=models.CASCADE, null=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.user.first_name} - {self.amount} сум ({self.status})"
    
    def mark_completed(self):
        """Mark payment as completed and process the purchase"""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save()
        
        # Process what they bought
        if self.service_type == 'premium' and self.property:
            self.property.is_premium = True
            self.property.save()
        elif self.service_type == 'top_up':
            self.user.balance += self.amount
            self.user.save()
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Payment"
        verbose_name_plural = "Payments"

class ClickTransaction(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE)
    click_trans_id = models.CharField(max_length=100)
    merchant_trans_id = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    action = models.CharField(max_length=20)  # prepare, complete
    error = models.IntegerField(default=0)
    error_note = models.CharField(max_length=200, blank=True)
    sign_time = models.CharField(max_length=20)
    sign_string = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Click Transaction"
        verbose_name_plural = "Click Transactions"

class PaymeTransaction(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE)
    payme_id = models.CharField(max_length=255, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    state = models.IntegerField()  # 1: created, 2: completed, negative: cancelled
    create_time = models.BigIntegerField()
    perform_time = models.BigIntegerField(null=True, blank=True)
    cancel_time = models.BigIntegerField(null=True, blank=True)
    reason = models.IntegerField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Payme Transaction"
        verbose_name_plural = "Payme Transactions"