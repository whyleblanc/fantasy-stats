import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    // keep this so you see it in the browser console too
    console.error("[ErrorBoundary]", error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div
        style={{
          padding: 16,
          borderRadius: 12,
          background: "rgba(15,23,42,0.9)",
          border: "1px solid #ef4444",
          color: "#fecaca",
        }}
      >
        <div style={{ fontWeight: 700, marginBottom: 8 }}>
          UI crashed while rendering this tab
        </div>
        <div style={{ color: "#e5e7eb", marginBottom: 8 }}>
          {this.state.error?.showMessage ? this.state.error.showMessage : String(this.state.error)}
        </div>
        <pre style={{ whiteSpace: "pre-wrap", color: "#9ca3af", fontSize: 12 }}>
          {this.state.error?.stack}
        </pre>
      </div>
    );
  }
}