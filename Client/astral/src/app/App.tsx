import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, type ReactNode } from 'react'
import { createBrowserRouter, Outlet, RouterProvider } from 'react-router'

import { ToastProvider } from '../components/ui/Toast'
import AuthLayout from '../pages/auth/AuthLayout'
import ForgotPassword from '../pages/auth/ForgotPassword'
import Register from '../pages/auth/Register'
import SignIn from '../pages/auth/SignIn'
import SsoCallback from '../pages/auth/SsoCallback'
import Landing from '../pages/Landing'
import RouteError from '../pages/RouteError'
import { AuthProvider } from './auth'
import { Home, RequireRole, RequireSignIn } from './guards'
import Layout from './Layout'
import { ScopeProvider } from './scope'

// App pages load on demand so the landing and sign-in pages don't wait for Leaflet and Recharts.
const Admin = lazy(() => import('../pages/Admin'))
const Assistant = lazy(() => import('../pages/Assistant'))
const Dashboard = lazy(() => import('../pages/Dashboard'))
const LiveMap = lazy(() => import('../pages/LiveMap'))
const MyReports = lazy(() => import('../pages/MyReports'))
const Priority = lazy(() => import('../pages/Priority'))
const Report = lazy(() => import('../pages/Report'))
const ReportStatus = lazy(() => import('../pages/ReportStatus'))
const RoadAnalysis = lazy(() => import('../pages/RoadAnalysis'))
const Zones = lazy(() => import('../pages/Zones'))

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

const STAFF = ['officer', 'viewer', 'admin'] as const
const staff = (page: ReactNode) => <RequireRole roles={[...STAFF]}>{page}</RequireRole>
const signedIn = (page: ReactNode) => <RequireSignIn>{page}</RequireSignIn>

// Clerk needs React Router's navigation, so auth lives inside the router's root route.
function Root() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Outlet />
      </ToastProvider>
    </AuthProvider>
  )
}

const router = createBrowserRouter([
  {
    element: <Root />,
    errorElement: <RouteError />,
    children: [
      {
        element: <AuthLayout />,
        children: [
          { path: 'sign-in', element: <SignIn /> },
          { path: 'register', element: <Register /> },
          { path: 'forgot-password', element: <ForgotPassword /> },
        ],
      },
      { path: 'welcome', element: <Landing /> },
      { path: 'sso-callback', element: <div className="p-8"><SsoCallback /></div> },
      {
        path: '/',
        element: <Layout />,
        children: [
          { index: true, element: <Home dashboard={<Dashboard />} /> },
          { path: 'map', element: <LiveMap /> },
          { path: 'report', element: signedIn(<Report />) },
          { path: 'report/:ref', element: signedIn(<ReportStatus />) },
          { path: 'my-reports', element: signedIn(<MyReports />) },
          { path: 'priority', element: staff(<Priority />) },
          { path: 'zones', element: staff(<Zones />) },
          { path: 'zones/:zoneId', element: staff(<Zones />) },
          { path: 'analysis', element: staff(<RoadAnalysis />) },
          { path: 'analysis/:segmentId', element: staff(<RoadAnalysis />) },
          { path: 'assistant', element: staff(<Assistant />) },
          { path: 'admin', element: <RequireRole roles={['admin']}><Admin /></RequireRole> },
        ],
      },
    ],
  },
])

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ScopeProvider>
        <RouterProvider router={router} />
      </ScopeProvider>
    </QueryClientProvider>
  )
}
