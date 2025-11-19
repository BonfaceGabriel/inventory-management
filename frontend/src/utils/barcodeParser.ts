/**
 * Barcode Parser Utility
 *
 * Parses barcode scans in various formats and extracts product information.
 * Supports flexible formats for different barcode types.
 */

export interface ParsedBarcode {
  sku?: string;
  prod_code?: string;
  quantity: number;
  rawValue: string;
}

/**
 * Parse a barcode string into structured data.
 *
 * Supported formats:
 * - Simple SKU: "AP004E" -> {sku: "AP004E", quantity: 1}
 * - SKU with quantity: "AP004E*2" -> {sku: "AP004E", quantity: 2}
 * - SKU with quantity (x): "AP004Ex2" -> {sku: "AP004E", quantity: 2}
 * - JSON format: '{"sku":"AP004E","quantity":2}' -> {sku: "AP004E", quantity: 2}
 *
 * @param barcodeValue - The raw barcode string
 * @returns Parsed barcode data
 */
export function parseBarcode(barcodeValue: string): ParsedBarcode {
  if (!barcodeValue || barcodeValue.trim() === '') {
    throw new Error('Barcode cannot be empty');
  }

  const trimmed = barcodeValue.trim();

  // Try JSON format first
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const parsed = JSON.parse(trimmed);
      return {
        sku: parsed.sku,
        prod_code: parsed.prod_code,
        quantity: parsed.quantity || 1,
        rawValue: trimmed,
      };
    } catch (e) {
      // Fall through to other parsing methods
    }
  }

  // Check for quantity modifiers: "SKU*qty" or "SKUxqty"
  const quantityMatch = trimmed.match(/^([A-Za-z0-9-_]+)[*x](\d+)$/i);
  if (quantityMatch) {
    return {
      sku: quantityMatch[1],
      quantity: parseInt(quantityMatch[2], 10),
      rawValue: trimmed,
    };
  }

  // Default: treat as simple SKU with quantity 1
  return {
    sku: trimmed,
    quantity: 1,
    rawValue: trimmed,
  };
}

/**
 * Validate a parsed barcode.
 *
 * @param parsed - The parsed barcode data
 * @returns True if valid, false otherwise
 */
export function isValidBarcode(parsed: ParsedBarcode): boolean {
  // Must have either SKU or prod_code
  if (!parsed.sku && !parsed.prod_code) {
    return false;
  }

  // Quantity must be positive
  if (parsed.quantity <= 0) {
    return false;
  }

  return true;
}

/**
 * Format a barcode for display.
 *
 * @param parsed - The parsed barcode data
 * @returns Formatted string for display
 */
export function formatBarcodeDisplay(parsed: ParsedBarcode): string {
  const identifier = parsed.sku || parsed.prod_code || 'Unknown';
  if (parsed.quantity > 1) {
    return `${identifier} × ${parsed.quantity}`;
  }
  return identifier;
}

/**
 * Sanitize barcode input (remove special characters that might cause issues).
 *
 * @param input - Raw input string
 * @returns Sanitized string
 */
export function sanitizeBarcodeInput(input: string): string {
  // Remove leading/trailing whitespace
  let sanitized = input.trim();

  // Remove common control characters (but keep JSON braces)
  sanitized = sanitized.replace(/[\x00-\x09\x0B-\x0C\x0E-\x1F\x7F]/g, '');

  return sanitized;
}
