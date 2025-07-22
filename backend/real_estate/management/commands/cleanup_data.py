from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from real_estate.models import Property, UserActivity
from payments.models import Payment

class Command(BaseCommand):
    help = 'Clean up old data and expired properties'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Delete activity older than specified days (default: 90)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        
        cutoff_date = timezone.now() - timedelta(days=days)
        
        # Clean up old user activities
        old_activities = UserActivity.objects.filter(created_at__lt=cutoff_date)
        activity_count = old_activities.count()
        
        # Clean up expired properties
        expired_properties = Property.objects.filter(
            expires_at__lt=timezone.now(),
            is_active=True
        )
        expired_count = expired_properties.count()
        
        # Clean up old failed payments
        old_failed_payments = Payment.objects.filter(
            status='failed',
            created_at__lt=cutoff_date
        )
        payment_count = old_failed_payments.count()
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN - No data will be deleted\n')
            )
            self.stdout.write(f"Would delete {activity_count} old activities")
            self.stdout.write(f"Would deactivate {expired_count} expired properties")
            self.stdout.write(f"Would delete {payment_count} old failed payments")
        else:
            # Delete old activities
            if activity_count > 0:
                old_activities.delete()
                self.stdout.write(
                    self.style.SUCCESS(f'Deleted {activity_count} old activities')
                )
            
            # Deactivate expired properties
            if expired_count > 0:
                expired_properties.update(is_active=False)
                self.stdout.write(
                    self.style.SUCCESS(f'Deactivated {expired_count} expired properties')
                )
            
            # Delete old failed payments
            if payment_count > 0:
                old_failed_payments.delete()
                self.stdout.write(
                    self.style.SUCCESS(f'Deleted {payment_count} old failed payments')
                )
            
            if activity_count == 0 and expired_count == 0 and payment_count == 0:
                self.stdout.write(
                    self.style.SUCCESS('No data to clean up')
                )