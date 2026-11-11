import { Component, type ErrorInfo, type ReactNode } from "react";
import { log } from "./log";

interface State {
  error: Error | null;
}

// Surfaces an error thrown inside its tree to the page and the console: in the 3D view, instead of
// react-three-fiber swallowing it into a blank canvas; around a dashboard page, so one failing page
// says so in place instead of unmounting the whole dashboard.
type Props = { children: ReactNode; what?: string; scope?: string; className?: string };
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    log.error(this.props.scope ?? "scene", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className={this.props.className ?? "error"} role="alert">
          <div>
            <strong>{this.props.what ?? "3D scene"} failed to render</strong>
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
