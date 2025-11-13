export interface Product {
  id: number;
  name: string;
  description: string;
  price: string;
  cost_price?: string;
  quantity: number;
  sku?: string;
  category?: string;
  supplier?: string;
  reorder_level?: number;
  image_url?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProductFormData {
  name: string;
  description: string;
  price: string;
  cost_price?: string;
  quantity: number;
  sku?: string;
  category?: string;
  supplier?: string;
  reorder_level?: number;
  is_active: boolean;
}

export interface ProductFilters {
  search?: string;
  category?: string;
  is_active?: boolean;
  low_stock?: boolean;
}
