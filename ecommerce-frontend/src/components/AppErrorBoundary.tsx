import { Component, type ErrorInfo, type ReactNode } from 'react'

interface AppErrorBoundaryProps {
  children: ReactNode
}

interface AppErrorBoundaryState {
  hasError: boolean
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Application rendering failed.', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="empty-state" role="alert">
          <p className="eyebrow">Something went wrong</p>
          <h1>This page could not be displayed.</h1>
          <p>Your account and saved data are unchanged. Reload to try again.</p>
          <button type="button" onClick={() => window.location.reload()}>Reload application</button>
        </main>
      )
    }
    return this.props.children
  }
}
