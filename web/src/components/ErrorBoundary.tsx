import { Component, type ErrorInfo, type ReactNode } from "react";
import { ErrorBanner, PageHeader, Panel } from "./ui";

interface ErrorBoundaryProps {
  children: ReactNode;
  resetKey?: string;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Route render failed", error, errorInfo);
  }

  componentDidUpdate(previousProps: ErrorBoundaryProps) {
    if (previousProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <>
          <PageHeader title="Route unavailable" />
          <Panel title="Console route">
            <ErrorBanner message={this.state.error.message || "This route failed to render"} />
            <p className="empty-state">The navigation shell is still available.</p>
          </Panel>
        </>
      );
    }

    return this.props.children;
  }
}
