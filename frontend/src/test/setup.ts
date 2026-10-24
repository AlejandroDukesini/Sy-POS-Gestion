import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
});

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })),
});

window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;

// jsdom no implementa <dialog>.showModal()
HTMLDialogElement.prototype.showModal = function showModal() { this.setAttribute('open', ''); };
HTMLDialogElement.prototype.close = function close() { this.removeAttribute('open'); };

vi.mock('virtual:pwa-register/react', () => ({
  useRegisterSW: () => ({ needRefresh: [false, () => undefined], offlineReady: [false, () => undefined], updateServiceWorker: vi.fn() }),
}));
