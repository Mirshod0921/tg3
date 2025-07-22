from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Payment, ClickTransaction, PaymeTransaction
from real_estate.models import TelegramUser, Property
import json
import logging
import hashlib
import hmac
import base64
from django.conf import settings
from time import timezone

logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def click_prepare(request):
    """Handle Click.uz prepare webhook"""
    try:
        data = json.loads(request.body)
        
        # Basic validation
        click_trans_id = data.get('click_trans_id')
        merchant_trans_id = data.get('merchant_trans_id')
        amount = float(data.get('amount', 0))
        
        # Find payment
        try:
            payment = Payment.objects.get(id=merchant_trans_id)
            
            if payment.status != 'pending':
                return JsonResponse({'error': -4, 'error_note': 'Payment already processed'})
            
            if float(payment.amount) != amount:
                return JsonResponse({'error': -2, 'error_note': 'Invalid amount'})
            
            # Create Click transaction record
            ClickTransaction.objects.create(
                payment=payment,
                click_trans_id=click_trans_id,
                merchant_trans_id=merchant_trans_id,
                amount=amount,
                action='prepare',
                error=0
            )
            
            return JsonResponse({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'error': 0,
                'error_note': 'Success'
            })
            
        except Payment.DoesNotExist:
            return JsonResponse({'error': -5, 'error_note': 'Payment not found'})
    
    except Exception as e:
        logger.error(f"Click prepare error: {e}")
        return JsonResponse({'error': -1, 'error_note': 'System error'})

@csrf_exempt
@require_POST
def click_complete(request):
    """Handle Click.uz complete webhook"""
    try:
        data = json.loads(request.body)
        
        click_trans_id = data.get('click_trans_id')
        merchant_trans_id = data.get('merchant_trans_id')
        error = data.get('error', 0)
        
        # Find payment
        try:
            payment = Payment.objects.get(id=merchant_trans_id)
            
            if error == 0:
                # Payment successful
                payment.status = 'completed'
                payment.transaction_id = click_trans_id
                payment.mark_completed()
                
                # Create transaction record
                ClickTransaction.objects.create(
                    payment=payment,
                    click_trans_id=click_trans_id,
                    merchant_trans_id=merchant_trans_id,
                    amount=float(data.get('amount', 0)),
                    action='complete',
                    error=0
                )
                
            else:
                # Payment failed
                payment.status = 'failed'
                payment.save()
            
            return JsonResponse({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'error': 0,
                'error_note': 'Success'
            })
            
        except Payment.DoesNotExist:
            return JsonResponse({'error': -5, 'error_note': 'Payment not found'})
    
    except Exception as e:
        logger.error(f"Click complete error: {e}")
        return JsonResponse({'error': -1, 'error_note': 'System error'})

@csrf_exempt
@require_POST
def payme_webhook(request):
    """Handle Payme.uz webhooks"""
    try:
        # Check authorization
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Basic '):
            return JsonResponse({
                'error': {
                    'code': -32504,
                    'message': 'Insufficient privileges'
                }
            })
        
        data = json.loads(request.body)
        method = data.get('method')
        params = data.get('params', {})
        request_id = data.get('id')
        
        if method == 'CheckPerformTransaction':
            return check_perform_transaction(params, request_id)
        elif method == 'CreateTransaction':
            return create_payme_transaction(params, request_id)
        elif method == 'PerformTransaction':
            return perform_payme_transaction(params, request_id)
        elif method == 'CancelTransaction':
            return cancel_payme_transaction(params, request_id)
        elif method == 'CheckTransaction':
            return check_payme_transaction(params, request_id)
        else:
            return JsonResponse({
                'error': {
                    'code': -32601,
                    'message': 'Method not found'
                }
            })
    
    except Exception as e:
        logger.error(f"Payme webhook error: {e}")
        return JsonResponse({
            'error': {
                'code': -32400,
                'message': 'Bad request'
            }
        })

def check_perform_transaction(params, request_id):
    """Check if transaction can be performed"""
    try:
        order_id = params.get('account', {}).get('order_id')
        amount = params.get('amount', 0) / 100  # Convert from tiyin
        
        try:
            payment = Payment.objects.get(id=order_id)
            
            if payment.status != 'pending':
                return JsonResponse({
                    'error': {
                        'code': -31008,
                        'message': 'Payment already processed'
                    }
                })
            
            if float(payment.amount) != amount:
                return JsonResponse({
                    'error': {
                        'code': -31001,
                        'message': 'Invalid amount'
                    }
                })
            
            return JsonResponse({
                'result': {
                    'allow': True
                },
                'id': request_id
            })
            
        except Payment.DoesNotExist:
            return JsonResponse({
                'error': {
                    'code': -31050,
                    'message': 'Payment not found'
                }
            })
    
    except Exception as e:
        logger.error(f"Check perform transaction error: {e}")
        return JsonResponse({
            'error': {
                'code': -32400,
                'message': 'Bad request'
            }
        })

def create_payme_transaction(params, request_id):
    """Create Payme transaction"""
    try:
        order_id = params.get('account', {}).get('order_id')
        amount = params.get('amount', 0) / 100
        transaction_id = params.get('id')
        
        payment = Payment.objects.get(id=order_id)
        
        # Check if transaction already exists
        payme_transaction, created = PaymeTransaction.objects.get_or_create(
            payme_id=transaction_id,
            defaults={
                'payment': payment,
                'amount': amount,
                'state': 1,
                'create_time': int(timezone.now().timestamp() * 1000)
            }
        )
        
        return JsonResponse({
            'result': {
                'create_time': payme_transaction.create_time,
                'transaction': str(payme_transaction.id),
                'state': payme_transaction.state
            },
            'id': request_id
        })
        
    except Payment.DoesNotExist:
        return JsonResponse({
            'error': {
                'code': -31050,
                'message': 'Payment not found'
            }
        })

def perform_payme_transaction(params, request_id):
    """Perform Payme transaction"""
    try:
        transaction_id = params.get('id')
        payme_transaction = PaymeTransaction.objects.get(payme_id=transaction_id)
        
        if payme_transaction.state == 1:
            payme_transaction.state = 2
            payme_transaction.perform_time = int(timezone.now().timestamp() * 1000)
            payme_transaction.save()
            
            # Update payment status
            payment = payme_transaction.payment
            payment.status = 'completed'
            payment.transaction_id = transaction_id
            payment.mark_completed()
        
        return JsonResponse({
            'result': {
                'transaction': str(payme_transaction.id),
                'perform_time': payme_transaction.perform_time,
                'state': payme_transaction.state
            },
            'id': request_id
        })
        
    except PaymeTransaction.DoesNotExist:
        return JsonResponse({
            'error': {
                'code': -31003,
                'message': 'Transaction not found'
            }
        })

def cancel_payme_transaction(params, request_id):
    """Cancel Payme transaction"""
    try:
        transaction_id = params.get('id')
        reason = params.get('reason', 0)
        
        payme_transaction = PaymeTransaction.objects.get(payme_id=transaction_id)
        
        if payme_transaction.state in [1, 2]:
            payme_transaction.state = -reason
            payme_transaction.cancel_time = int(timezone.now().timestamp() * 1000)
            payme_transaction.save()
            
            # Update payment status
            payment = payme_transaction.payment
            payment.status = 'cancelled'
            payment.save()
        
        return JsonResponse({
            'result': {
                'transaction': str(payme_transaction.id),
                'cancel_time': payme_transaction.cancel_time,
                'state': payme_transaction.state
            },
            'id': request_id
        })
        
    except PaymeTransaction.DoesNotExist:
        return JsonResponse({
            'error': {
                'code': -31003,
                'message': 'Transaction not found'
            }
        })

def check_payme_transaction(params, request_id):
    """Check Payme transaction status"""
    try:
        transaction_id = params.get('id')
        payme_transaction = PaymeTransaction.objects.get(payme_id=transaction_id)
        
        result = {
            'create_time': payme_transaction.create_time,
            'transaction': str(payme_transaction.id),
            'state': payme_transaction.state
        }
        
        if payme_transaction.perform_time:
            result['perform_time'] = payme_transaction.perform_time
        
        if payme_transaction.cancel_time:
            result['cancel_time'] = payme_transaction.cancel_time
        
        return JsonResponse({
            'result': result,
            'id': request_id
        })
        
    except PaymeTransaction.DoesNotExist:
        return JsonResponse({
            'error': {
                'code': -31003,
                'message': 'Transaction not found'
            }
        })

@api_view(['POST'])
@permission_classes([AllowAny])
def create_payment(request):
    """Create new payment"""
    try:
        telegram_id = request.data.get('user_id')
        amount = request.data.get('amount')
        payment_method = request.data.get('payment_method')
        service_type = request.data.get('service_type')
        property_id = request.data.get('property_id')
        
        if not all([telegram_id, amount, payment_method, service_type]):
            return Response({'error': 'Missing required fields'}, status=400)
        
        user = TelegramUser.objects.get(telegram_id=telegram_id)
        property_obj = None
        if property_id:
            property_obj = Property.objects.get(id=property_id)
        
        payment = Payment.objects.create(
            user=user,
            amount=amount,
            payment_method=payment_method,
            service_type=service_type,
            property=property_obj,
            status='pending'
        )
        
        # Generate payment URL (simplified)
        if payment_method == 'click':
            payment_url = f"https://my.click.uz/services/pay?service_id=example&merchant_id={payment.id}"
        else:
            payment_url = f"https://checkout.paycom.uz/{payment.id}"
        
        return Response({
            'payment_id': payment.id,
            'payment_url': payment_url,
            'status': payment.status
        })
        
    except Exception as e:
        logger.error(f"Create payment error: {e}")
        return Response({'error': 'Failed to create payment'}, status=400)

@api_view(['GET'])
@permission_classes([AllowAny])
def payment_status(request, payment_id):
    """Check payment status"""
    try:
        payment = Payment.objects.get(id=payment_id)
        return Response({
            'payment_id': payment.id,
            'status': payment.status,
            'amount': payment.amount,
            'created_at': payment.created_at
        })
    except Payment.DoesNotExist:
        return Response({'error': 'Payment not found'}, status=404)
