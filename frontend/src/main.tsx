import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Link, RouterProvider } from 'react-router-dom'

import './index.css'
import { Layout } from './components/Layout'
import { RequireReviewer } from './components/RequireReviewer'
import { DocumentsPage } from './pages/DocumentsPage'
import { LoginPage } from './pages/LoginPage'
import { QueuePage } from './pages/QueuePage'
import { ReviewPage } from './pages/ReviewPage'
import { RulesPage } from './pages/RulesPage'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } } })

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: (
      <RequireReviewer>
        <Layout />
      </RequireReviewer>
    ),
    children: [
      { path: '/', element: <QueuePage /> },
      { path: '/review/:id', element: <ReviewPage /> },
      { path: '/documents', element: <DocumentsPage /> },
      { path: '/rules', element: <RulesPage /> },
      {
        path: '*',
        element: (
          <p className="text-muted">
            Page not found. <Link to="/" className="text-brand">Back to the queue</Link>
          </p>
        ),
      },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
