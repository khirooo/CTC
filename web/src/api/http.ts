export class CtcApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
    this.name = 'CtcApiError';
  }
}

export async function apiFetch(
  base: string,
  userId: string,
  path: string,
  init?: RequestInit,
): Promise<any> {
  const res = await fetch(base + path, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-CTC-User': userId,
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let code = 'error';
    let message = res.statusText;
    try {
      const body = await res.json();
      // Backend error shape is flat: { error: "<code>", message: "<text>" }
      if (typeof body?.error === 'string') code = body.error;
      if (typeof body?.message === 'string') message = body.message;
    } catch {
      /* non-JSON error body */
    }
    throw new CtcApiError(code, message, res.status);
  }
  if (res.status === 204) return undefined;
  return res.json();
}
