import { Component, type ReactNode } from 'react';

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };
  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }
  override componentDidCatch(): void {
    /* No sensitive error data is rendered. */
  }
  override render(): ReactNode {
    if (this.state.failed)
      return (
        <main className="centered-page">
          <span className="message-code">Error</span>
          <h1>The workspace could not open</h1>
          <p>Reload the page. If the problem continues, contact the internal service owner.</p>
          <button
            className="button"
            onClick={() => {
              window.location.assign('/');
            }}
          >
            Reload workspace
          </button>
        </main>
      );
    return this.props.children;
  }
}
