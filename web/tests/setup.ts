import '@testing-library/jest-dom';

// Polyfill a fully functional localStorage for the jsdom/Node test environment.
// Node 25 has a native localStorage stub, but it lacks .clear() and .removeItem()
// unless --localstorage-file is provided. We replace it with a Map-backed mock.
const makeLocalStorageMock = (): Storage => {
  const store = new Map<string, string>();
  return {
    get length() { return store.size; },
    key(index: number): string | null {
      return Array.from(store.keys())[index] ?? null;
    },
    getItem(key: string): string | null {
      return store.get(key) ?? null;
    },
    setItem(key: string, value: string): void {
      store.set(key, String(value));
    },
    removeItem(key: string): void {
      store.delete(key);
    },
    clear(): void {
      store.clear();
    },
  };
};

Object.defineProperty(globalThis, 'localStorage', {
  value: makeLocalStorageMock(),
  writable: true,
  configurable: true,
});
