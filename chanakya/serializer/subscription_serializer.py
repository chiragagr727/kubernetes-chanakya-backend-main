from rest_framework import serializers
from chanakya.models.subscription_model import UserSubscription


class UserSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSubscription
        fields = ['id', 'provider_type', 'active', 'start_date', 'expiry_date', 'subscription_duration', 'created_at',
                  'updated_at']
        read_only_fields = ['id', 'subscription_duration', 'created_at', 'updated_at']

    def create(self, validated_data):
        user = self.context['request'].user
        return UserSubscription.objects.create(user=user, **validated_data)
