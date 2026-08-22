from decimal import Decimal
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from payments.models import Promotion
from .test_helpers import make_admin, make_authenticated_client


class PromotionAPITest(APITestCase):
    def setUp(self):
        self.admin = make_admin(username='promo_api_admin')
        self.client = make_authenticated_client(self.admin)

    def test_list_promotions(self):
        Promotion.objects.create(
            name='Test Promo API',
            discount_type='FIXED',
            discount_value=Decimal('200.00'),
            start_date=timezone.now() - timezone.timedelta(days=1),
            end_date=timezone.now() + timezone.timedelta(days=30),
            created_by=self.admin,
        )
        response = self.client.get(reverse('promotion-list-create'))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data), 0)

    def test_create_promotion(self):
        response = self.client.post(reverse('promotion-list-create'), {
            'name': 'New Promo',
            'discount_type': 'FIXED',
            'discount_value': '500.00',
            'start_date': (timezone.now() - timezone.timedelta(days=1)).isoformat(),
            'end_date': (timezone.now() + timezone.timedelta(days=30)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_get_promotion_detail(self):
        promo = Promotion.objects.create(
            name='Detail Promo',
            discount_type='PERCENTAGE',
            discount_value=Decimal('10.00'),
            start_date=timezone.now() - timezone.timedelta(days=1),
            end_date=timezone.now() + timezone.timedelta(days=30),
            created_by=self.admin,
        )
        url = reverse('promotion-detail', args=[promo.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_update_promotion(self):
        promo = Promotion.objects.create(
            name='Update Promo',
            discount_type='FIXED',
            discount_value=Decimal('200.00'),
            start_date=timezone.now() - timezone.timedelta(days=1),
            end_date=timezone.now() + timezone.timedelta(days=30),
            created_by=self.admin,
        )
        url = reverse('promotion-detail', args=[promo.id])
        response = self.client.patch(url, {'discount_value': '300.00'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_delete_promotion(self):
        promo = Promotion.objects.create(
            name='Delete Promo',
            discount_type='FIXED',
            discount_value=Decimal('100.00'),
            start_date=timezone.now(),
            end_date=timezone.now() + timezone.timedelta(days=30),
            created_by=self.admin,
        )
        url = reverse('promotion-detail', args=[promo.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 204)

    def test_create_promotion_missing_required_fields(self):
        response = self.client.post(reverse('promotion-list-create'), {
            'name': 'Bad Promo',
        }, format='json')
        self.assertEqual(response.status_code, 400)
