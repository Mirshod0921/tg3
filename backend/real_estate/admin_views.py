from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
from .models import TelegramUser, Property, UserActivity
from payments.models import Payment
import json

@staff_member_required
def admin_analytics(request):
    """Advanced analytics page for admin"""
    
    # Date range for analytics
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)
    
    # User analytics
    user_growth = []
    property_growth = []
    
    for i in range(30):
        date = start_date + timedelta(days=i)
        user_count = TelegramUser.objects.filter(created_at__date=date.date()).count()
        property_count = Property.objects.filter(created_at__date=date.date()).count()
        
        user_growth.append({
            'date': date.strftime('%Y-%m-%d'),
            'count': user_count
        })
        property_growth.append({
            'date': date.strftime('%Y-%m-%d'),
            'count': property_count
        })
    
    # Revenue analytics
    revenue_data = Payment.objects.filter(
        status='completed',
        created_at__gte=start_date
    ).values('created_at__date').annotate(
        daily_revenue=Sum('amount')
    ).order_by('created_at__date')
    
    # Popular regions
    region_stats = Property.objects.values('region').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Activity heatmap
    activity_heatmap = UserActivity.objects.filter(
        created_at__gte=start_date
    ).values('action').annotate(
        count=Count('id')
    ).order_by('-count')
    
    context = {
        'user_growth': json.dumps(user_growth),
        'property_growth': json.dumps(property_growth),
        'revenue_data': list(revenue_data),
        'region_stats': region_stats,
        'activity_heatmap': activity_heatmap,
        'date_range': {
            'start': start_date.strftime('%Y-%m-%d'),
            'end': end_date.strftime('%Y-%m-%d')
        }
    }
    
    return render(request, 'admin/analytics.html', context)

@staff_member_required
def bulk_operations(request):
    """Bulk operations page for admin"""
    
    if request.method == 'POST':
        operation = request.POST.get('operation')
        
        if operation == 'approve_all_pending':
            count = Property.objects.filter(is_approved=False).update(is_approved=True)
            messages.success(request, f'Approved {count} pending properties')
        
        elif operation == 'deactivate_expired':
            count = Property.objects.filter(
                expires_at__lt=timezone.now(),
                is_active=True
            ).update(is_active=False)
            messages.success(request, f'Deactivated {count} expired properties')
        
        elif operation == 'cleanup_old_activities':
            cutoff = timezone.now() - timedelta(days=90)
            count = UserActivity.objects.filter(created_at__lt=cutoff).count()
            UserActivity.objects.filter(created_at__lt=cutoff).delete()
            messages.success(request, f'Deleted {count} old activities')
        
        return redirect('admin:bulk_operations')
    
    # Get counts for display
    pending_properties = Property.objects.filter(is_approved=False).count()
    expired_properties = Property.objects.filter(
        expires_at__lt=timezone.now(),
        is_active=True
    ).count()
    old_activities = UserActivity.objects.filter(
        created_at__lt=timezone.now() - timedelta(days=90)
    ).count()
    
    context = {
        'pending_properties': pending_properties,
        'expired_properties': expired_properties,
        'old_activities': old_activities,
    }
    
    return render(request, 'admin/bulk_operations.html', context)