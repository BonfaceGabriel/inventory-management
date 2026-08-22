from django.urls import reverse
from rest_framework.test import APITestCase
from .test_helpers import (
    make_admin, make_processor, make_location,
    make_authenticated_client,
)


class LocationAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin(username='loc_admin')
        self.client = make_authenticated_client(self.admin)
        self.location = make_location()

    def test_list_locations(self):
        response = self.client.get(reverse('location-list-create'))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data), 0)

    def test_create_location(self):
        response = self.client.post(reverse('location-list-create'), {
            'name': 'New Location',
            'location_type': 'FIELD',
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_create_location_duplicate_name(self):
        response = self.client.post(reverse('location-list-create'), {
            'name': 'Main Shop',
            'location_type': 'FIELD',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_get_location_detail(self):
        url = reverse('location-detail', args=[self.location.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_update_location(self):
        url = reverse('location-detail', args=[self.location.id])
        response = self.client.patch(url, {'notes': 'Updated notes'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_close_location(self):
        url = reverse('location-close', args=[self.location.id])
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_set_user_location(self):
        response = self.client.post(reverse('location-set-mine'), {
            'location_id': str(self.location.id),
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.current_location.id, self.location.id)

    def test_set_user_location_not_found(self):
        response = self.client.post(reverse('location-set-mine'), {
            'location_id': '00000000-0000-0000-0000-000000000000',
        }, format='json')
        self.assertEqual(response.status_code, 404)
