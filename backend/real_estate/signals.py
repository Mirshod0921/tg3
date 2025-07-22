# backend/real_estate/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import TelegramUser, Property
from payments.models import Payment
import logging

logger = logging.getLogger('real_estate')

@receiver(post_save, sender=Property)
def log_property_changes(sender, instance, created, **kwargs):
    """Log property creation and updates"""
    try:
        action = "created" if created else "updated"
        logger.info(f"Property {action}: {instance.title} (ID: {instance.id}) by user {instance.user.telegram_id}")
    except Exception as e:
        logger.error(f"Error logging property changes: {e}")

@receiver(post_save, sender=Payment)
def log_payment_changes(sender, instance, created, **kwargs):
    """Log payment status changes"""
    try:
        if created:
            logger.info(f"Payment created: {instance.amount} UZS by user {instance.user.telegram_id}")
        else:
            logger.info(f"Payment updated: {instance.id} status changed to {instance.status}")
    except Exception as e:
        logger.error(f"Error logging payment changes: {e}")

@receiver(post_save, sender=TelegramUser)
def log_user_changes(sender, instance, created, **kwargs):
    """Log user registration and updates"""
    try:
        if created:
            logger.info(f"New user registered: {instance.telegram_id} ({instance.first_name})")
        else:
            logger.info(f"User updated: {instance.telegram_id} ({instance.first_name})")
    except Exception as e:
        logger.error(f"Error logging user changes: {e}")

@receiver(post_delete, sender=Property)
def log_property_deletion(sender, instance, **kwargs):
    """Log property deletions"""
    try:
        logger.warning(f"Property deleted: {instance.title} (ID: {instance.id})")
    except Exception as e:
        logger.error(f"Error logging property deletion: {e}")