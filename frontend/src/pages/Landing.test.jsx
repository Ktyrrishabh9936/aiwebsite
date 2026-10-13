import { act } from 'react';
import { createRoot } from 'react-dom/client';

import { ThemeProvider } from '../context/ThemeContext';
import Landing from './Landing';
import api from '../lib/api';

jest.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: null }) }));
jest.mock('../lib/api', () => ({
  __esModule: true,
  default: { post: jest.fn() },
  formatError: value => String(value || 'Something went wrong.'),
}));
jest.mock('react-router-dom', () => ({
  Link: ({ to, children, ...props }) => <a href={to} {...props}>{children}</a>,
}), { virtual: true });
let container;
let root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  api.post.mockReset();
  api.post.mockResolvedValue({ data: { message: 'Thank you! Our team will contact you shortly.' } });
  window.history.pushState({}, '', '/?utm_source=google&utm_medium=cpc&utm_campaign=october&utm_term=crm&utm_content=footer&gclid=g-1&fbclid=f-1');
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
test('submits the landing form to CRM with UTM and click attribution', async () => {
  const form = container.querySelector('.am-form');
  form.querySelector('[name="full_name"]').value = 'Sarah Mitchell';
  form.querySelector('[name="email"]').value = 'sarah@example.com';
  form.querySelector('[name="phone"]').value = '+919876543210';
  await act(async () => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(api.post).toHaveBeenCalledWith('/public/forms/lf_LoZNTme6VpmS9k1xg2t3F5d/submit', expect.objectContaining({
    full_name: 'Sarah Mitchell', email: 'sarah@example.com', phone: '+919876543210',
    utm_source: 'google', utm_medium: 'cpc', utm_campaign: 'october', utm_term: 'crm', utm_content: 'footer',
    gclid: 'g-1', fbclid: 'f-1', page_url: expect.stringContaining('utm_source=google'),
  }));
  expect(form.querySelector('[role="status"]').textContent).toContain('Thank you');
});

