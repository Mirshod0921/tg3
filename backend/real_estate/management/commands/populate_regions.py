from django.core.management.base import BaseCommand
from real_estate.models import Region, District

class Command(BaseCommand):
    help = 'Populate regions and districts with updated data structure'

    def handle(self, *args, **options):
        # Clear existing data
        District.objects.all().delete()
        Region.objects.all().delete()
        
        # Uzbekistan regions with keys
        regions_data = [
            {
                'key': 'tashkent_city',
                'name_uz': 'Toshkent shahri',
                'name_ru': 'Город Ташкент',
                'name_en': 'Tashkent City',
                'districts': [
                    ('bektemir', 'Bektemir', 'Бектемир', 'Bektemir'),
                    ('chilonzor', 'Chilonzor', 'Чиланзар', 'Chilanzar'),
                    ('mirobod', 'Mirobod', 'Мирабад', 'Mirobod'),
                    ('mirzo_ulugbek', 'Mirzo Ulug\'bek', 'Мирзо Улугбек', 'Mirzo Ulugbek'),
                    ('olmazor', 'Olmazor', 'Алмазар', 'Olmazor'),
                    ('sergeli', 'Sergeli', 'Сергели', 'Sergeli'),
                    ('shayxontohur', 'Shayxontohur', 'Шайхантахур', 'Shaykhantakhur'),
                    ('uchtepa', 'Uchtepa', 'Учтепа', 'Uchtepa'),
                    ('yakkasaroy', 'Yakkasaroy', 'Яккасарай', 'Yakkasaray'),
                    ('yunusobod', 'Yunusobod', 'Юнусабад', 'Yunusabad'),
                    ('yashnobod', 'Yashnobod', 'Яшнабад', 'Yashnabad'),
                ]
            },
            {
                'key': 'tashkent_region',
                'name_uz': 'Toshkent viloyati',
                'name_ru': 'Ташкентская область',
                'name_en': 'Tashkent Region',
                'districts': [
                    ('angren', 'Angren', 'Ангрен', 'Angren'),
                    ('bekobod', 'Bekobod', 'Бекабад', 'Bekabad'),
                    ('bostonliq', 'Bo\'stonliq', 'Бустанлык', 'Bostanlyk'),
                    ('chinoz', 'Chinoz', 'Чиназ', 'Chinaz'),
                    ('qibray', 'Qibray', 'Кибрай', 'Kibray'),
                    ('oqqorgon', 'Oqqo\'rg\'on', 'Аккурган', 'Akkurgan'),
                    ('olmaliq', 'Olmaliq', 'Алмалык', 'Almalyk'),
                    ('ohangaron', 'Ohangaron', 'Ахангаран', 'Akhangaran'),
                    ('parkent', 'Parkent', 'Паркент', 'Parkent'),
                    ('piskent', 'Piskent', 'Пскент', 'Piskent'),
                    ('yangiyol', 'Yangiyo\'l', 'Янгиюль', 'Yangiyul'),
                    ('zangiota', 'Zangiota', 'Зангиота', 'Zangiata'),
                ]
            },
            {
                'key': 'samarkand',
                'name_uz': 'Samarqand viloyati',
                'name_ru': 'Самаркандская область',
                'name_en': 'Samarkand Region',
                'districts': [
                    ('samarkand', 'Samarqand', 'Самарканд', 'Samarkand'),
                    ('bulungur', 'Bulung\'ur', 'Булунгур', 'Bulungur'),
                    ('ishtixon', 'Ishtixon', 'Иштыхан', 'Ishtykhan'),
                    ('jomboy', 'Jomboy', 'Джамбай', 'Jambay'),
                    ('kattaqorgon', 'Kattaqo\'rg\'on', 'Каттакурган', 'Kattakurgan'),
                    ('narpay', 'Narpay', 'Нарпай', 'Narpay'),
                    ('nurobod', 'Nurobod', 'Нурабад', 'Nurabad'),
                    ('oqdaryo', 'Oqdaryo', 'Акдарья', 'Akdarya'),
                    ('urgut', 'Urgut', 'Ургут', 'Urgut'),
                ]
            }
        ]
        
        for region_data in regions_data:
            region = Region.objects.create(
                key=region_data['key'],
                name_uz=region_data['name_uz'],
                name_ru=region_data['name_ru'],
                name_en=region_data['name_en'],
            )
            
            self.stdout.write(f"Created region: {region.name_uz}")
            
            # Create districts
            for district_data in region_data['districts']:
                district = District.objects.create(
                    region=region,
                    key=district_data[0],
                    name_uz=district_data[1],
                    name_ru=district_data[2],
                    name_en=district_data[3],
                )
                
                self.stdout.write(f"  Created district: {district.name_uz}")
        
        self.stdout.write(
            self.style.SUCCESS('Successfully populated regions and districts')
        )