from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from real_estate.models import TelegramUser, Property
import asyncio
import aiohttp

class Command(BaseCommand):
    help = 'Send notifications to users'

    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            type=str,
            choices=['expiring', 'inactive', 'custom'],
            required=True,
            help='Type of notification to send'
        )
        parser.add_argument('--message', type=str, help='Custom message to send')
        parser.add_argument('--bot-token', type=str, help='Telegram bot token')

    def handle(self, *args, **options):
        notification_type = options['type']
        custom_message = options['message']
        bot_token = options['bot_token']
        
        if not bot_token:
            self.stdout.write(
                self.style.ERROR('Bot token is required')
            )
            return
        
        if notification_type == 'expiring':
            self.send_expiring_notifications(bot_token)
        elif notification_type == 'inactive':
            self.send_inactive_notifications(bot_token)
        elif notification_type == 'custom':
            if not custom_message:
                self.stdout.write(
                    self.style.ERROR('Custom message is required for custom notifications')
                )
                return
            self.send_custom_notifications(bot_token, custom_message)

    def send_expiring_notifications(self, bot_token):
        # Properties expiring in 3 days
        expiring_date = timezone.now() + timedelta(days=3)
        expiring_properties = Property.objects.filter(
            expires_at__lte=expiring_date,
            expires_at__gt=timezone.now(),
            is_active=True
        )
        
        for property in expiring_properties:
            message = f"⚠️ Your property '{property.title}' will expire soon. Please renew to keep it active."
            asyncio.run(self.send_telegram_message(bot_token, property.user.telegram_id, message))
        
        self.stdout.write(
            self.style.SUCCESS(f'Sent expiring notifications to {expiring_properties.count()} users')
        )

    def send_inactive_notifications(self, bot_token):
        # Users inactive for 30 days
        inactive_date = timezone.now() - timedelta(days=30)
        inactive_users = TelegramUser.objects.filter(
            activities__created_at__lt=inactive_date,
            is_blocked=False
        ).distinct()
        
        message = "👋 We miss you! Check out the latest properties on our bot."
        
        count = 0
        for user in inactive_users:
            asyncio.run(self.send_telegram_message(bot_token, user.telegram_id, message))
            count += 1
        
        self.stdout.write(
            self.style.SUCCESS(f'Sent inactive notifications to {count} users')
        )

    def send_custom_notifications(self, bot_token, message):
        active_users = TelegramUser.objects.filter(is_blocked=False)
        
        count = 0
        for user in active_users:
            asyncio.run(self.send_telegram_message(bot_token, user.telegram_id, message))
            count += 1
        
        self.stdout.write(
            self.style.SUCCESS(f'Sent custom notifications to {count} users')
        )

    async def send_telegram_message(self, bot_token, chat_id, message):
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as response:
                    if response.status == 200:
                        return True
                    else:
                        self.stdout.write(
                            self.style.ERROR(f'Failed to send message to {chat_id}')
                        )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error sending message to {chat_id}: {e}')
            )
        
        return False