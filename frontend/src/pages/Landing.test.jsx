import { act } from 'react';
import { createRoot } from 'react-dom/client';

import { ThemeProvider } from '../context/ThemeContext';
import Landing from './Landing';

jest.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: null }) }));
const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => ({
  Link: ({ to, children, ...props }) => <a href={to} {...props}>{children}</a>,
  useNavigate: () => mockNavigate,
}), { virtual: true });
let container;
let root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  mockNavigate.mockClear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root.render(<ThemeProvider><Landing/></ThemeProvider>));
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});
test('renders all navigation targets and switches the persisted theme', () => {
  for (const link of container.querySelectorAll('a[href^="#"]')) {
    expect(container.querySelector(link.getAttribute('href'))).not.toBeNull();
  }
  expect(document.documentElement.classList.contains('dark')).toBe(true);
  act(() => container.querySelector('[data-testid="theme-toggle"]').click());
  expect(document.documentElement.classList.contains('dark')).toBe(false);
  expect(localStorage.getItem('arevei_theme')).toBe('light');
});
test('switches annual prices and expands mobile navigation', () => {
  expect(container.querySelector('.am-price').textContent).toBe('$97/month');
  act(() => container.querySelectorAll('.am-billing-toggle button')[1].click());
  expect(container.querySelector('.am-price').textContent).toBe('$970/year');
  act(() => container.querySelector('.am-menu').click());
  expect(container.querySelector('.am-menu').getAttribute('aria-expanded')).toBe('true');
  expect(container.querySelector('#mobile-nav').classList.contains('is-open')).toBe(true);
});
test('passes lead details to account setup without pretending to subscribe', () => {
  const form = container.querySelector('.am-form');
  form.querySelector('[name="name"]').value = 'Sarah Mitchell';
  form.querySelector('[name="email"]').value = 'sarah@example.com';
  act(() => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(mockNavigate).toHaveBeenCalledWith(expect.stringContaining("/register?"), { state: { name: "Sarah Mitchell", email: "sarah@example.com" } });
});

