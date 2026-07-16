import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from '../auth/AuthContext';
import { AppRoutes } from '../routes/AppRoutes';
import { ErrorBoundary } from './ErrorBoundary';
import { WorkflowProvider } from '../workflow/WorkflowContext';

export function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <WorkflowProvider>
            <AppRoutes />
          </WorkflowProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
