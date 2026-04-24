const CLOUD_SUFFIX = '.eagleshop.cloud';

const normalize = (value?: string): string => (value || '').trim();

const deriveCloudApiHost = (hostname: string): string | null => {
  if (!hostname.endsWith(CLOUD_SUFFIX)) {
    return null;
  }

  const subdomain = hostname.split('.')[0];
  if (!subdomain) {
    return null;
  }

  // Legacy main app domain remains api.eagleshop.cloud.
  if (subdomain === 'app') {
    return 'api.eagleshop.cloud';
  }

  // Shop domains like kitengela.eagleshop.cloud -> kitengela-api.eagleshop.cloud.
  return `${subdomain}-api.eagleshop.cloud`;
};

export const resolveApiBaseUrl = (): string => {
  const envApi = normalize(import.meta.env.VITE_API_URL);

  if (typeof window === 'undefined') {
    return envApi || 'http://localhost:8000/api/v1';
  }

  const derivedHost = deriveCloudApiHost(window.location.hostname);
  if (derivedHost) {
    return `https://${derivedHost}/api/v1`;
  }

  return envApi || 'http://localhost:8000/api/v1';
};

export const resolveWebSocketBaseUrl = (): string => {
  const envWs = normalize(import.meta.env.VITE_WS_URL);

  if (typeof window === 'undefined') {
    return envWs || 'ws://localhost:8000';
  }

  const derivedHost = deriveCloudApiHost(window.location.hostname);
  if (derivedHost) {
    return `wss://${derivedHost}`;
  }

  return envWs || 'ws://localhost:8000';
};
