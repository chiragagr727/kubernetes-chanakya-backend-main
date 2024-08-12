from rest_framework import serializers
from django.contrib.auth import get_user_model
from chanakya.models.subscription_model import UserSubscription

User = get_user_model()


class UserSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSubscription
        fields = ['provider_type', 'active', 'type', 'start_date', 'expiry_date', 'created_at', 'updated_at',
                  'subscription_paused', 'subscription_cancel', 'subscription_expire']


class UserSerializer(serializers.ModelSerializer):
    subscriptions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['is_subscription_active', 'subscriptions']

    def get_subscriptions(self, obj):
        subscriptions = UserSubscription.objects.filter(user=obj, active=True)
        return UserSubscriptionSerializer(subscriptions, many=True).data
