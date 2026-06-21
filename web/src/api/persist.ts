import type { StoreState } from '@/api/seed';

const VERSION = 1;

interface Wrapper {
  v: number;
  state: StoreState;
}

export function load(key: string): StoreState | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed: Wrapper = JSON.parse(raw);
    if (!parsed || parsed.v !== VERSION) return null;
    return parsed.state;
  } catch {
    return null;
  }
}

export function save(key: string, state: StoreState): void {
  const wrapper: Wrapper = { v: VERSION, state };
  localStorage.setItem(key, JSON.stringify(wrapper));
}
