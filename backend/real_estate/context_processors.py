# backend/real_estate/context_processors.py
from django.conf import settings
from .models import TelegramUser, Property
from payments.models import Payment

def admin_stats(request):
    """Add global statistics to admin context"""
    if not request.path.startswith('/admin/'):
        return {}
    
    try:
        stats = {
            'total_users': TelegramUser.objects.count(),
            'total_properties': Property.objects.count(),
            'active_properties': Property.objects.filter(is_approved=True, is_active=True).count(),
            'premium_properties': Property.objects.filter(is_premium=True).count(),
            'pending_count': Property.objects.filter(is_approved=False).count(),
            'total_payments': Payment.objects.count(),
            'completed_payments': Payment.objects.filter(status='completed').count(),
        }
        return {'admin_stats': stats}
    except Exception as e:
        return {'admin_stats': {}}