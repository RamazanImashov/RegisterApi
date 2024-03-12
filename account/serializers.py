from rest_framework import serializers
from rest_framework.serializers import ValidationError
from django.contrib.auth import get_user_model, authenticate
from .tasks import send_activation_code_celery, send_password_celery

# from .models import Category


User = get_user_model()



class RegisterSerializer(serializers.ModelSerializer):
    password_confirm = serializers.CharField(min_length=6, required=True)

    class Meta:
        model = User
        fields = ["email", "password", "password_confirm"]

    def validate(self, attrs):
        password = attrs.get("password")
        password_confirm = attrs.pop("password_confirm")
        if password != password_confirm:
            raise ValidationError("Password not confirm")
        return attrs

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        send_activation_code_celery.delay(user.email, user.activation_code)
        return user


class ActivationSerializer(serializers.Serializer):
    email = serializers.CharField()
    code = serializers.CharField()

    def validate(self, attrs):
        email = attrs.get("email")
        code = attrs.get("code")
        if not User.objects.filter(email=email, activation_code=code).exists():
            raise serializers.ValidationError("Пользователь не найден")
        return attrs

    def activate(self):
        email = self.validated_data.get("email")
        user = User.objects.get(email=email)
        user.is_active = True
        user.activation_code = ""
        user.save()


class LoginSerializer(serializers.ModelSerializer):
    email = serializers.CharField(required=True)
    password = serializers.CharField(required=True)

    def validate_email(self, email):
        if not User.objects.filter(email=email).exists():
            raise ValidationError("User not found")
        return email

    def validate(self, attrs):
        request = self.context.get("request")
        email = attrs.get("email")
        password = attrs.get("password")

        if email and password:
            user = authenticate(username=email, password=password, request=request)

            if not user:
                raise ValidationError("Error email or password")

        else:
            raise ValidationError("Email and password obazatelno")

        attrs["user"] = user
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(min_length=4, required=True)
    new_password = serializers.CharField(min_length=4, required=True)
    new_password_confirm = serializers.CharField(min_length=4, required=True)

    def validate_old_password(self, old_password):
        request = self.context.get("request")
        user = request.user
        if not user.check_password(old_password):
            raise serializers.ValidationError("Введите корректный пароль")
        return old_password

    def validate(self, attrs):
        old_password = attrs.get("old_password")
        new_password = attrs.get("new_password")
        new_password_confirm = attrs.get("new_password_confirm")

        if new_password != new_password_confirm:
            raise serializers.ValidationError("Пароли не совпадают")
        if new_password == old_password:
            raise serializers.ValidationError("Старый и новый пароли совпадают")
        return attrs

    def set_new_password(self):
        new_password = self.validated_data.get("new_password")
        user = self.context.get("request").user
        user.set_password(new_password)
        user.save()


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate(self, attrs):
        email = attrs.get("email")

        if not User.objects.filter(email=email).exists():
            raise serializers.ValidationError("Пользователь с таким email не найден")
        return attrs

    def send_verification_email(self):
        email = self.validated_data.get("email")
        user = User.objects.get(email=email)
        user.create_forgot_password_code()
        send_password_celery.delay(user.email, user.forgot_password_code)


class ForgotPasswordCompleteSerializer(serializers.Serializer):
    code = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(min_length=4, required=True)
    password_confirm = serializers.CharField(min_length=4, required=True)

    def validate(self, attrs):
        email = attrs.get("email")
        code = attrs.get("code")
        password = attrs.get("password")
        password_confirm = attrs.pop("password_confirm")

        if not User.objects.filter(email=email, forgot_password_code=code).exists():
            raise serializers.ValidationError(
                "Пользователь не найден или неправильный код"
            )
        if password != password_confirm:
            raise serializers.ValidationError("Пароли не совпадают")
        return attrs

    def set_new_password(self):
        email = self.validated_data.get("email")
        password = self.validated_data.get("password")
        user = User.objects.get(email=email)
        user.set_password(password)
        user.forgot_password_code = ""
        user.save()
