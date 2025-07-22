from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    # Click.uz webhooks
    path('click/prepare/', views.click_prepare, name='click-prepare'),
    path('click/complete/', views.click_complete, name='click-complete'),
    
    # Payme.uz webhooks
    path('payme/', views.payme_webhook, name='payme-webhook'),
    
    # API endpoints
    path('api/create/', views.create_payment, name='create-payment'),
    path('api/status/<int:payment_id>/', views.payment_status, name='payment-status'),
]