// Dev-only visual QA entry (served at /preview.html by `vite dev`).
// Mounts the real app tree on the seeded in-memory fakeApi from tests/, so
// every screen renders with realistic data and no control plane. Sign in with
// any seeded name (e.g. "yuki" for a Host, "lena" for a Guest).
import React from 'react';
import ReactDOM from 'react-dom/client';
import { createHashRouter, RouterProvider } from 'react-router-dom';
import './theme/globals.css';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AppProvider } from '@/store/AppContext';
import { AppRoutes } from '@/app/routes';
import { makeFakeApi } from '../tests/helpers/fakeApi';

// Hash router so the harness works from /preview.html without server-side
// history fallback (client paths live behind the #).
const router = createHashRouter([{ path: '*', element: <AppRoutes /> }]);
const api = makeFakeApi();

// ?user=lena / ?user=yuki … pre-signs-in a seeded user so role-specific
// screens (Guest profile, admin) can be eyeballed directly.
const who = new URLSearchParams(window.location.search).get('user');
if (who) await api.signIn(who, 'x');

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <AppProvider api={api}>
        <RouterProvider router={router} />
      </AppProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
