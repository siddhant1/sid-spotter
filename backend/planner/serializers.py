from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers


class PlaceSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=300)
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class PlanRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure = serializers.DateTimeField()
    load_lb = serializers.FloatField(min_value=0, max_value=200_000)
    interval_mi = serializers.ChoiceField(choices=[10, 25, 50], default=25)
    hos = serializers.BooleanField(default=False)
    simulate_storm = serializers.BooleanField(default=False)

    def validate_departure(self, value):
        now = timezone.now()
        if value < now - timedelta(hours=1):
            raise serializers.ValidationError("Departure can't be in the past.")
        if value > now + timedelta(days=settings.MAX_DEPARTURE_DAYS_AHEAD):
            raise serializers.ValidationError(
                f"Departure must be within {settings.MAX_DEPARTURE_DAYS_AHEAD} days. Forecasts beyond that are unreliable."
            )
        return value

    def validate(self, attrs):
        o, d = attrs["origin"], attrs["destination"]
        if abs(o["lat"] - d["lat"]) < 1e-4 and abs(o["lon"] - d["lon"]) < 1e-4:
            raise serializers.ValidationError("Origin and destination are the same place.")
        return attrs


class StormSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)
    peak_epoch = serializers.FloatField()


class HeatmapRequestSerializer(serializers.Serializer):
    corridor = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2),
        min_length=2,
        max_length=5000,
    )
    departure = serializers.DateTimeField()
    load_lb = serializers.FloatField(min_value=0, max_value=200_000)
    storm = StormSerializer(required=False, allow_null=True)
