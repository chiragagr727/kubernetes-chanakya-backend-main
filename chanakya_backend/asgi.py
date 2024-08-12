# import os
# from channels.routing import ProtocolTypeRouter, URLRouter
# from premium_features.views.poc_views import ChatConsumer
# from django.urls import path
#
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chanakya_backend.settings.development')
#
# application = ProtocolTypeRouter({
#     'websocket': URLRouter([
#         path('ws/chanakya/poc/', ChatConsumer.as_asgi()),
#     ])
# })