from django.urls import reverse
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from .test_helpers import make_admin, make_processor, make_authenticated_client

User = get_user_model()


class UserAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin(username='user_admin')
        self.client = make_authenticated_client(self.admin)

    def test_list_users(self):
        make_processor(username='user_proc')
        response = self.client.get(reverse('user-list-create'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_create_user(self):
        response = self.client.post(reverse('user-list-create'), {
            'username': 'new_user',
            'password': 'testpass123',
            'role': 'ISSUER',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(username='new_user').exists())

    def test_create_user_missing_password(self):
        response = self.client.post(reverse('user-list-create'), {
            'username': 'no_pass_user',
            'role': 'ISSUER',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_get_user_detail(self):
        response = self.client.get(reverse('user-detail', args=[self.admin.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'user_admin')

    def test_update_user(self):
        response = self.client.patch(
            reverse('user-detail', args=[self.admin.id]),
            {'first_name': 'Updated'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name, 'Updated')

    def test_delete_user(self):
        user = make_processor(username='delete_user')
        response = self.client.delete(reverse('user-detail', args=[user.id]))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(username='delete_user').exists())

    def test_admin_reset_password(self):
        user = make_processor(username='reset_user')
        response = self.client.post(
            reverse('admin-reset-password', args=[user.id]),
            {'new_password': 'newpass123'}, format='json',
        )
        self.assertEqual(response.status_code, 200)

    def test_processor_cannot_list_users(self):
        processor = make_processor(username='proc_no_list')
        proc_client = make_authenticated_client(processor)
        response = proc_client.get(reverse('user-list-create'))
        self.assertEqual(response.status_code, 403)
