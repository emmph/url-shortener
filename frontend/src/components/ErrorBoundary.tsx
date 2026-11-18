import React from 'react'
import { Navigate } from 'react-router-dom'

interface Props {
  children: React.ReactNode
}

interface State {
  hasError: boolean
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return <Navigate to="/error/500?reason=server_error" replace />
    }
    return this.props.children
  }
}
