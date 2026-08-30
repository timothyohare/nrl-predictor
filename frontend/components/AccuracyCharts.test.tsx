import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import AccuracyCharts from "./AccuracyCharts";
import type { MetricRecord } from "@/lib/api";

// recharts' ResponsiveContainer renders nothing at 0x0 (jsdom has no layout),
// which would hide the chart subtree. Stub it with a fixed-size passthrough so
// the chart content mounts and we can assert on it.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 800, height: 220 }}>{children}</div>
    ),
  };
});

const metric = (over: Partial<MetricRecord>): MetricRecord => ({
  period: "round-1",
  metricName: "pick_rate",
  value: 0.5,
  ...over,
});

describe("AccuracyCharts", () => {
  it("renders both charts when pick-rate and margin-error data are present", () => {
    const rounds: MetricRecord[] = [
      metric({ period: "round-1", metricName: "pick_rate", value: 0.625 }),
      metric({ period: "round-2", metricName: "pick_rate", value: 0.5 }),
      metric({ period: "round-1", metricName: "mean_margin_error", value: 8.2 }),
      metric({ period: "round-2", metricName: "mean_margin_error", value: 11.9 }),
    ];
    render(<AccuracyCharts rounds={rounds} />);
    expect(screen.getByText("Pick Rate by Round (%)")).toBeInTheDocument();
    expect(screen.getByText("Mean Margin Error by Round (pts)")).toBeInTheDocument();
  });

  it("renders only the pick-rate chart when there is no margin-error data", () => {
    const rounds: MetricRecord[] = [
      metric({ period: "round-1", metricName: "pick_rate", value: 0.7 }),
    ];
    render(<AccuracyCharts rounds={rounds} />);
    expect(screen.getByText("Pick Rate by Round (%)")).toBeInTheDocument();
    expect(
      screen.queryByText("Mean Margin Error by Round (pts)"),
    ).not.toBeInTheDocument();
  });

  it("renders nothing when there is no pick-rate data (empty state)", () => {
    const { container } = render(<AccuracyCharts rounds={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when rounds contain only unrelated metrics", () => {
    const { container } = render(
      <AccuracyCharts
        rounds={[metric({ metricName: "brier_score", value: 0.2 })]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
