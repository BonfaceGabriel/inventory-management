from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from .test_helpers import make_admin, make_processor, make_issuer

User = get_user_model()


class AuthAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_admin(username='login_admin')
        self.admin.set_password('testpass123')
        self.admin.save()

    def test_login_success(self):
        response = self.client.post(reverse('auth-login'), {
            'username': 'login_admin',
            'password': 'testpass123',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_fails_with_wrong_password(self):
        response = self.client.post(reverse('auth-login'), {
            'username': 'login_admin',
            'password': 'wrongpassword',
        }, format='json')
        self.assertEqual(response.status_code, 401)

    def test_login_fails_with_nonexistent_user(self):
        response = self.client.post(reverse('auth-login'), {
            'username': 'nonexistent',
            'password': 'testpass123',
        }, format='json')
        self.assertEqual(response.status_code, 401)

    def test_refresh_token(self):
        response = self.client.post(reverse('auth-login'), {
            'username': 'login_admin',
            'password': 'testpass123',
        }, format='json')
        refresh = response.data['refresh']
        response = self.client.post(reverse('auth-refresh'), {
            'refresh': refresh,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)

    def test_refresh_with_invalid_token(self):
        response = self.client.post(reverse('auth-refresh'), {
            'refresh': 'invalid_token_here',
        }, format='json')
        self.assertEqual(response.status_code, 401)

    def test_logout_requires_auth(self):
        response = self.client.post(reverse('auth-logout'))
        self.assertEqual(response.status_code, 401)

    def test_logout_success(self):
        response = self.client.post(reverse('auth-login'), {
            'username': 'login_admin',
            'password': 'testpass123',
        }, format='json')
        access = response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        response = self.client.post(reverse('auth-logout'), {
            'refresh': response.data['refresh'],
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_get_profile(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(reverse('auth-profile'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'login_admin')

    def test_update_profile(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(reverse('auth-profile'), {
            'first_name': 'Updated',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name, 'Updated')

    def test_change_password(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(reverse('auth-change-password'), {
            'old_password': 'testpass123',
            'new_password': 'newpass456',
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_change_password_with_wrong_old_password(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(reverse('auth-change-password'), {
            'old_password': 'wrongold',
            'new_password': 'newpass456',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_profile_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('auth-profile'))
        self.assertEqual(response.status_code, 401)
