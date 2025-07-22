# backend/real_estate/middleware.py
from django.utils.deprecation import MiddlewareMixin
import logging

logger = logging.getLogger('django.contrib.admin')

class AdminActionLoggingMiddleware(MiddlewareMixin):
    """Enhanced logging for admin actions"""
    
    def process_response(self, request, response):
        try:
            if (request.path.startswith('/admin/') and 
                request.user.is_authenticated and 
                request.user.is_staff):
                
                # Log admin page visits
                if request.method == 'GET':
                    logger.info(f"Admin page visited: {request.path} by {request.user.username}")
                
                # Log form submissions
                elif request.method == 'POST':
                    logger.info(f"Admin form submitted: {request.path} by {request.user.username}")
        except Exception as e:
            logger.error(f"Error in admin logging middleware: {e}")
        
        return response