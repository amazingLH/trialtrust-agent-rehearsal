import ReactDOM from 'react-dom/client';
import { RouterProvider } from '@tanstack/react-router';
import { getRouter } from './router';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <RouterProvider router={getRouter()} />,
);
