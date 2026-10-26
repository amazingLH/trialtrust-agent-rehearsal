/** Browser-safe public endpoint. No platform or model credentials live here. */
const endpoint = 'https://l666h666better-trialtrust.ms.show/api/browser-bridge';
const allowedHeaders = new Set([
  'x-trialtrust-account', 'x-trialtrust-browser', 'x-trialtrust-session',
  'x-trialtrust-conversation',
]);

export async function bridgeFetch(path: string, options: RequestInit = {}): Promise<Response> {
  if (!path.startsWith('/api/')) throw new Error('请求地址不正确');
  const headers: Record<string, string> = {};
  new Headers(options.headers).forEach((value, key) => {
    if (allowedHeaders.has(key)) headers[key] = value;
  });
  // Never retry writes automatically. Existing account errors retain their status.
  return globalThis.fetch(endpoint, {
    method: 'POST', mode: 'cors', credentials: 'omit', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    signal: options.signal,
    body: JSON.stringify({
      path, method: options.method || 'GET', headers,
      body: options.body == null ? null : JSON.parse(String(options.body)),
    }),
  });
}
