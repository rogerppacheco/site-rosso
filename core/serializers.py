from rest_framework import serializers
from .models import RegraAutomacao

class RegraAutomacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegraAutomacao
        fields = '__all__'