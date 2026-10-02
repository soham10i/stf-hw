import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  error: Error | null;
}

// Surfaces any error thrown inside the 3D tree to the page and the console,
// instead of letting react-three-fiber's internal handling swallow it into a
// blank canvas.
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("3D scene error:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="error">
          <div>
            <strong>3D scene failed to render</strong>
            <pre style={{ whiteSpace: "pre-wrap", maxWidth: 600 }}>
              {this.state.error.message}
            </pre>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
