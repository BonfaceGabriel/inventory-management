/**
 * Barcode Parser Utility
 *
 * Parses barcode scans in various formats and extracts product information.
 * Supports flexible formats for different barcode types.
 */

export interface ParsedBarcode {
  sku?: string;
  prod_code?: string;
  barcode?: string;
  quantity: number;
  rawValue: string;
}

/**
 * Parse a barcode string into structured data.
 *
 * Supported formats:
 * - Numeric barcode: "893663002920" -> {barcode: "893663002920", quantity: 1}
 * - Alphanumeric SKU: "AP004E" -> {sku: "AP004E", quantity: 1}
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
        barcode: parsed.barcode,
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
    const identifier = quantityMatch[1];
    const qty = parseInt(quantityMatch[2], 10);

    // Check if identifier is purely numeric (barcode) or alphanumeric (SKU)
    if (/^\d+$/.test(identifier)) {
      return {
        barcode: identifier,
        quantity: qty,
        rawValue: trimmed,
      };
    } else {
      return {
        sku: identifier,
        quantity: qty,
        rawValue: trimmed,
      };
    }
  }

  // Check if the value is purely numeric (likely a barcode)
  if (/^\d+$/.test(trimmed)) {
    return {
      barcode: trimmed,
      quantity: 1,
      rawValue: trimmed,
    };
  }

  // Default: treat as alphanumeric SKU with quantity 1
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
  // Must have either SKU, prod_code, or barcode
  if (!parsed.sku && !parsed.prod_code && !parsed.barcode) {
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
  const identifier = parsed.sku || parsed.prod_code || parsed.barcode || 'Unknown';
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
