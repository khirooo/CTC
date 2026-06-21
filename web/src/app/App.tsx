import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { AppProvider } from '@/store/AppContext';
import { AppRoutes } from './routes';

/**
 * Browser router instance for production use.
 * We use a catch-all route that renders AppRoutes so all path matching
 * is handled inside AppRoutes itself (using <Routes>).
 */
const router = createBrowserRouter([
  {
    path: '*',
    element: <AppRoutes />,
  },
]);

/**
 * Root application component.
 * Wraps the full tree with ThemeProvider → AppProvider → RouterProvider.
 */
export function App() {
  return (
    <ThemeProvider>
      <AppProvider>
        <RouterProvider router={router} />
      </AppProvider>
    </ThemeProvider>
  );
}
