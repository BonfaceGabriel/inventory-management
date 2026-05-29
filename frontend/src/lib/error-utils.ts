export function extractApiError(error: unknown, fallback = 'An error occurred'): string {
  if (!error || typeof error !== 'object') return fallback;

  const err = error as { response?: { data?: unknown }; message?: string };
  const data = err.response?.data;

  if (!data) return err.message || fallback;
  if (typeof data === 'string') return data;

  const obj = data as Record<string, unknown>;

  if (typeof obj.error === 'string') return obj.error;

  if (Array.isArray(obj.error)) return obj.error.join(', ');

  if (obj.error && typeof obj.error === 'object') {
    const vals = Object.values(obj.error as Record<string, unknown>).flat();
    if (vals.length) return vals.map(String).join(', ');
  }

  if (typeof obj.detail === 'string') return obj.detail;

  if (typeof obj.message === 'string') return obj.message;

  return fallback;
}

export function extractApiErrorVerbose(error: unknown): string {
  if (!error || typeof error !== 'object') return 'An error occurred';
  const data = (error as { response?: { data?: unknown } }).response?.data;
  if (data && typeof data === 'object') {
    const lines: string[] = [];
    for (const [key, val] of Object.entries(data as Record<string, unknown>)) {
      if (Array.isArray(val)) lines.push(`${key}: ${val.join(', ')}`);
      else if (typeof val === 'string') lines.push(`${key}: ${val}`);
    }
    return lines.join(' | ') || 'An error occurred';
  }
  return (error as { message?: string }).message || 'An error occurred';
}
