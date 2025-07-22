def get_listing_template(user_lang: str, status: str, property_type: str) -> str:
    """Generate template based on property type and status"""
    
    # Special templates for Land and Commercial (regardless of sale/rent)
    if property_type == 'land':
        if user_lang == 'uz':
            return """
E'lon mazmunini yozing.
Shu namuna asosida e'loningizni yozing!

🧱 Bo'sh yer sotiladi yoki olinadi
📍 Hudud: Toshkent viloyati, Zangiota tumani
📐 Maydoni: 6 sotix
📄 Hujjatlari: tayyor, kadastr bor
🚗 Yo'l: asfalt yo'lga yaqin
💧Kommunikatsiya: suv, svet yaqin
💰 Narxi: 35 000$
(Qo'shimcha ma'lumot kiritish mumkin)

🔴 Eslatma
Ma'lumotlar qatorida tel raqamingizni bot so'ramaguncha yozmang, aks holda sizni telingiz jiringlashdan to'xtamaydi va biz siz yuborgan xabarni botdan o'chirib tashlash imkonsiz
"""
        elif user_lang == 'ru':
            return """
Напишите содержание объявления.
Пишите свое объявление по этому образцу!

🧱 Продается или покупается пустой участок
📍 Район: Ташкентская область, Зангиатинский район
📐 Площадь: 6 соток
📄 Документы: готовы, есть кадастр
🚗 Дорога: близко к асфальтированной дороге
💧Коммуникации: вода, свет рядом
💰 Цена: 35 000$
(Можно добавить дополнительную информацию)

🔴 Примечание
Не пишите свой номер телефона в тексте, пока бот не попросит, иначе ваш телефон не перестанет звонить и мы не сможем удалить ваше сообщение из бота
"""
        else:  # English
            return """
Write the content of the listing.
Write your listing based on this template!

🧱 Empty land for sale or purchase
📍 Area: Tashkent region, Zangiata district
📐 Area: 6 acres
📄 Documents: ready, cadastre available
🚗 Road: close to paved road
💧Communications: water, electricity nearby
💰 Price: $35,000
(Additional information can be added)

🔴 Note
Do not write your phone number in the text until the bot asks for it, otherwise your phone will not stop ringing and we cannot delete your message from the bot
"""
    
    elif property_type == 'commercial':
        if user_lang == 'uz':
            return """
E'lon mazmunini yozing.
Shu namuna asosida e'loningizni yozing!

🏢 Do'kon sotiladi
📍 Tuman: Sergeli
📐 Maydoni: 35 m²
📄 Hujjat: noturar bino sifatida rasmiylashtirilgan
📌 Hozirda faoliyat yuritmoqda (ijarachi bor)
💰 Narxi: 60 000$
(Qo'shimcha ma'lumot kiritish mumkin)

🔴 Eslatma
Ma'lumotlar qatorida tel raqamingizni bot so'ramaguncha yozmang, aks holda sizni telingiz jiringlashdan to'xtamaydi va biz siz yuborgan xabarni botdan o'chirib tashlash imkonsiz
"""
        elif user_lang == 'ru':
            return """
Напишите содержание объявления.
Пишите свое объявление по этому образцу!

🏢 Продается магазин
📍 Район: Сергели
📐 Площадь: 35 м²
📄 Документ: оформлен как нежилое здание
📌 В настоящее время работает (есть арендатор)
💰 Цена: 60 000$
(Можно добавить дополнительную информацию)

🔴 Примечание
Не пишите свой номер телефона в тексте, пока бот не попросит, иначе ваш телефон не перестанет звонить и мы не сможем удалить ваше сообщение из бота
"""
        else:  # English
            return """
Write the content of the listing.
Write your listing based on this template!

🏢 Shop for sale
📍 District: Sergeli
📐 Area: 35 m²
📄 Document: registered as non-residential building
📌 Currently operating (tenant available)
💰 Price: $60,000
(Additional information can be added)

🔴 Note
Do not write your phone number in the text until the bot asks for it, otherwise your phone will not stop ringing and we cannot delete your message from the bot
"""
    
    # Regular templates for apartment/house based on sale/rent
    else:
        if user_lang == 'uz':
            if status == 'rent':
                return """
E'lon mazmunini yozing.
Shu namuna asosida e'loningizni yozing!

🏠 KVARTIRA IJARAGA BERILADI
📍 Shahar, Tuman 5-kvartal
💰 Narxi: 300$–400$
🛏 Xonalar: 2 xonali
♨️ Kommunal: gaz, suv, svet bor
🪚 Holati: yevro remont yoki o'rtacha
🛋 Jihoz: jihozli yoki jihozsiz
🕒 Muddat: qisqa yoki uzoq muddatga
👥 Kimga: Shariy nikohga / oilaga / studentlarga

🔴 Eslatma
Ma'lumotlar qatorida tel raqamingizni bot so'ramaguncha yozmang, aks holda sizni telingiz jiringlashdan to'xtamaydi va biz siz yuborgan xabarni botdan o'chirib tashlash imkonsiz
"""
            else:  # sale
                return """
E'lon mazmunini yozing.
Shu namuna asosida e'loningizni yozing!

🏠 UY-JOY SOTILADI 
📍 Shahar, Tuman
💰 Narxi: 50,000$–80,000$
🛏 Xonalar: 3 xonali
📐 Maydon: 65 m²
♨️ Kommunal: gaz, suv, svet bor
🪚 Holati: yevro remont yoki o'rtacha
🛋 Jihoz: jihozli yoki jihozsiz
🏢 Qavat: 3/9

🔴 Eslatma
Ma'lumotlar qatorida tel raqamingizni bot so'ramaguncha yozmang, aks holda sizni telingiz jiringlashdan to'xtamaydi va biz siz yuborgan xabarni botdan o'chirib tashlash imkonsiz
"""
        elif user_lang == 'ru':
            if status == 'rent':
                return """
Напишите содержание объявления.
Пишите свое объявление по этому образцу!

🏠 КВАРТИРА СДАЕТСЯ В АРЕНДУ
📍 Город, Район 5-квартал
💰 Цена: 300$–400$
🛏 Комнаты: 2-комнатная
♨️ Коммунальные: газ, вода, свет есть
🪚 Состояние: евроремонт или среднее
🛋 Мебель: с мебелью или без мебели
🕒 Срок: краткосрочно или долгосрочно
👥 Для кого: для гражданского брака / для семьи / для студентов

🔴 Примечание
Не пишите свой номер телефона в тексте, пока бот не попросит, иначе ваш телефон не перестанет звонить и мы не сможем удалить ваше сообщение из бота
"""
            else:  # sale
                return """
Напишите содержание объявления.
Пишите свое объявление по этому образцу!

🏠 ПРОДАЕТСЯ НЕДВИЖИМОСТЬ
📍 Город, Район
💰 Цена: 50,000$–80,000$
🛏 Комнаты: 3-комнатная
📐 Площадь: 65 м²
♨️ Коммунальные: газ, вода, свет есть
🪚 Состояние: евроремонт или среднее
🛋 Мебель: с мебелью или без мебели
🏢 Этаж: 3/9

🔴 Примечание
Не пишите свой номер телефона в тексте, пока бот не попросит, иначе ваш телефон не перестанет звонить и мы не сможем удалить ваше сообщение из бота
"""
        else:  # English
            if status == 'rent':
                return """
Write the content of the listing.
Write your listing based on this template!

🏠 APARTMENT FOR RENT
📍 City, District 5th Quarter
💰 Price: $300–$400
🛏 Rooms: 2-room
♨️ Utilities: gas, water, electricity available
🪚 Condition: euro renovation or average
🛋 Furniture: furnished or unfurnished
🕒 Period: short-term or long-term
👥 For whom: for civil marriage / for family / for students

🔴 Note
Do not write your phone number in the text until the bot asks for it, otherwise your phone will not stop ringing and we cannot delete your message from the bot
"""
            else:  # sale
                return """
Write the content of the listing.
Write your listing based on this template!

🏠 PROPERTY FOR SALE
📍 City, District
💰 Price: $50,000–$80,000
🛏 Rooms: 3-room
📐 Area: 65 m²
♨️ Utilities: gas, water, electricity available
🪚 Condition: euro renovation or average
🛋 Furniture: furnished or unfurnished
🏢 Floor: 3/9

🔴 Note
Do not write your phone number in the text until the bot asks for it, otherwise your phone will not stop ringing and we cannot delete your message from the bot
"""