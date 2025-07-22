from django.core.management.base import BaseCommand
from django.db.models import Count, Sum, Avg
from django.utils import timezone
from datetime import timedelta
from real_estate.models import TelegramUser, Property, Favorite, UserActivity
from payments.models import Payment

class Command(BaseCommand):
    help = 'Generate comprehensive admin statistics'

    def add_arguments(self, parser):
        parser.add_argument(
            '--format',
            type=str,
            choices=['table', 'json'],
            default='table',
            help='Output format (table or json)'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to analyze (default: 30)'
        )

    def handle(self, *args, **options):
        format_type = options['format']
        days = options['days']
        
        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Gather statistics
        stats = self.gather_statistics(start_date, end_date)
        
        if format_type == 'json':
            import json
            self.stdout.write(json.dumps(stats, indent=2, default=str))
        else:
            self.print_table_stats(stats, days)

    def gather_statistics(self, start_date, end_date):
        # User statistics
        total_users = TelegramUser.objects.count()
        active_users = TelegramUser.objects.filter(
            activities__created_at__gte=start_date
        ).distinct().count()
        blocked_users = TelegramUser.objects.filter(is_blocked=True).count()
        
        # Property statistics
        total_properties = Property.objects.count()
        active_properties = Property.objects.filter(
            is_approved=True, is_active=True
        ).count()
        premium_properties = Property.objects.filter(is_premium=True).count()
        pending_properties = Property.objects.filter(is_approved=False).count()
        
        # Recent activity
        new_users = TelegramUser.objects.filter(
            created_at__gte=start_date
        ).count()
        new_properties = Property.objects.filter(
            created_at__gte=start_date
        ).count()
        
        # Payment statistics
        total_payments = Payment.objects.count()
        completed_payments = Payment.objects.filter(status='completed').count()
        total_revenue = Payment.objects.filter(
            status='completed'
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        
        # Popular properties
        popular_properties = Property.objects.annotate(
            favorite_count=Count('favorited_by')
        ).order_by('-favorite_count')[:5]
        
        # User activity breakdown
        activity_breakdown = UserActivity.objects.filter(
            created_at__gte=start_date
        ).values('action').annotate(count=Count('id')).order_by('-count')
        
        return {
            'users': {
                'total': total_users,
                'active': active_users,
                'blocked': blocked_users,
                'new': new_users,
            },
            'properties': {
                'total': total_properties,
                'active': active_properties,
                'premium': premium_properties,
                'pending': pending_properties,
                'new': new_properties,
            },
            'payments': {
                'total': total_payments,
                'completed': completed_payments,
                'revenue': float(total_revenue),
            },
            'popular_properties': [
                {
                    'id': p.id,
                    'title': p.title,
                    'favorites': p.favorite_count,
                    'user': p.user.first_name or p.user.username,
                }
                for p in popular_properties
            ],
            'activity_breakdown': list(activity_breakdown),
            'date_range': {
                'start': start_date,
                'end': end_date,
                'days': (end_date - start_date).days,
            }
        }

    def print_table_stats(self, stats, days):
        self.stdout.write(
            self.style.SUCCESS(f'\n=== Real Estate Bot Statistics (Last {days} days) ===\n')
        )
        
        # User Statistics
        self.stdout.write(self.style.WARNING('USER STATISTICS:'))
        self.stdout.write(f"Total Users: {stats['users']['total']}")
        self.stdout.write(f"Active Users: {stats['users']['active']}")
        self.stdout.write(f"Blocked Users: {stats['users']['blocked']}")
        self.stdout.write(f"New Users: {stats['users']['new']}\n")
        
        # Property Statistics
        self.stdout.write(self.style.WARNING('PROPERTY STATISTICS:'))
        self.stdout.write(f"Total Properties: {stats['properties']['total']}")
        self.stdout.write(f"Active Properties: {stats['properties']['active']}")
        self.stdout.write(f"Premium Properties: {stats['properties']['premium']}")
        self.stdout.write(f"Pending Approval: {stats['properties']['pending']}")
        self.stdout.write(f"New Properties: {stats['properties']['new']}\n")
        
        # Payment Statistics
        self.stdout.write(self.style.WARNING('PAYMENT STATISTICS:'))
        self.stdout.write(f"Total Payments: {stats['payments']['total']}")
        self.stdout.write(f"Completed Payments: {stats['payments']['completed']}")
        self.stdout.write(f"Total Revenue: {stats['payments']['revenue']:,.2f} UZS\n")
        
        # Popular Properties
        self.stdout.write(self.style.WARNING('POPULAR PROPERTIES:'))
        for prop in stats['popular_properties']:
            self.stdout.write(
                f"• {prop['title'][:40]} - {prop['favorites']} favorites (by {prop['user']})"
            )
        
        # Activity Breakdown
        self.stdout.write(self.style.WARNING('\nACTIVITY BREAKDOWN:'))
        for activity in stats['activity_breakdown']:
            self.stdout.write(f"• {activity['action']}: {activity['count']} times")