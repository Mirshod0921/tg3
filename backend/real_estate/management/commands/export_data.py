import csv
import json
from django.core.management.base import BaseCommand
from django.http import HttpResponse
from real_estate.models import TelegramUser, Property
from payments.models import Payment

class Command(BaseCommand):
    help = 'Export data to CSV or JSON format'

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            type=str,
            choices=['users', 'properties', 'payments', 'all'],
            default='all',
            help='Model to export (default: all)'
        )
        parser.add_argument(
            '--format',
            type=str,
            choices=['csv', 'json'],
            default='csv',
            help='Export format (default: csv)'
        )
        parser.add_argument(
            '--output',
            type=str,
            help='Output file path'
        )

    def handle(self, *args, **options):
        model = options['model']
        format_type = options['format']
        output_path = options['output']
        
        if model == 'all':
            self.export_all_data(format_type, output_path)
        elif model == 'users':
            self.export_users(format_type, output_path)
        elif model == 'properties':
            self.export_properties(format_type, output_path)
        elif model == 'payments':
            self.export_payments(format_type, output_path)

    def export_all_data(self, format_type, output_path):
        data = {
            'users': self.get_users_data(),
            'properties': self.get_properties_data(),
            'payments': self.get_payments_data(),
        }
        
        if format_type == 'json':
            filename = output_path or 'real_estate_export.json'
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str, ensure_ascii=False)
            self.stdout.write(
                self.style.SUCCESS(f'All data exported to {filename}')
            )
        else:
            # Export each model to separate CSV files
            self.export_users('csv', f"{output_path or 'users'}.csv")
            self.export_properties('csv', f"{output_path or 'properties'}.csv")
            self.export_payments('csv', f"{output_path or 'payments'}.csv")

    def export_users(self, format_type, output_path):
        users_data = self.get_users_data()
        filename = output_path or f'users_export.{format_type}'
        
        if format_type == 'json':
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(users_data, f, indent=2, default=str, ensure_ascii=False)
        else:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                if users_data:
                    writer = csv.DictWriter(f, fieldnames=users_data[0].keys())
                    writer.writeheader()
                    writer.writerows(users_data)
        
        self.stdout.write(
            self.style.SUCCESS(f'Users exported to {filename}')
        )

    def export_properties(self, format_type, output_path):
        properties_data = self.get_properties_data()
        filename = output_path or f'properties_export.{format_type}'
        
        if format_type == 'json':
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(properties_data, f, indent=2, default=str, ensure_ascii=False)
        else:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                if properties_data:
                    writer = csv.DictWriter(f, fieldnames=properties_data[0].keys())
                    writer.writeheader()
                    writer.writerows(properties_data)
        
        self.stdout.write(
            self.style.SUCCESS(f'Properties exported to {filename}')
        )

    def export_payments(self, format_type, output_path):
        payments_data = self.get_payments_data()
        filename = output_path or f'payments_export.{format_type}'
        
        if format_type == 'json':
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(payments_data, f, indent=2, default=str, ensure_ascii=False)
        else:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                if payments_data:
                    writer = csv.DictWriter(f, fieldnames=payments_data[0].keys())
                    writer.writeheader()
                    writer.writerows(payments_data)
        
        self.stdout.write(
            self.style.SUCCESS(f'Payments exported to {filename}')
        )

    def get_users_data(self):
        users = TelegramUser.objects.all()
        return [
            {
                'id': user.id,
                'telegram_id': user.telegram_id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'language': user.language,
                'is_blocked': user.is_blocked,
                'balance': float(user.balance),
                'properties_count': user.properties.count(),
                'favorites_count': user.favorites.count(),
                'created_at': user.created_at,
                'updated_at': user.updated_at,
            }
            for user in users
        ]

    def get_properties_data(self):
        properties = Property.objects.select_related('user')
        return [
            {
                'id': prop.id,
                'user_telegram_id': prop.user.telegram_id,
                'user_name': prop.user.first_name,
                'title': prop.title,
                'description': prop.description,
                'property_type': prop.property_type,
                'region': prop.region,
                'district': prop.district,
                'address': prop.address,
                'full_address': prop.full_address,
                'price': float(prop.price),
                'area': prop.area,
                'rooms': prop.rooms,
                'condition': prop.condition,
                'status': prop.status,
                'contact_info': prop.contact_info,
                'is_premium': prop.is_premium,
                'is_approved': prop.is_approved,
                'is_active': prop.is_active,
                'views_count': prop.views_count,
                'favorites_count': prop.favorited_by.count(),
                'created_at': prop.created_at,
                'updated_at': prop.updated_at,
                'expires_at': prop.expires_at,
            }
            for prop in properties
        ]

    def get_payments_data(self):
        payments = Payment.objects.select_related('user', 'property')
        return [
            {
                'id': payment.id,
                'user_telegram_id': payment.user.telegram_id,
                'user_name': payment.user.first_name,
                'amount': float(payment.amount),
                'payment_method': payment.payment_method,
                'service_type': payment.service_type,
                'status': payment.status,
                'transaction_id': payment.transaction_id,
                'external_id': payment.external_id,
                'property_id': payment.property.id if payment.property else None,
                'property_title': payment.property.title if payment.property else None,
                'description': payment.description,
                'created_at': payment.created_at,
                'completed_at': payment.completed_at,
            }
            for payment in payments
        ]