import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import NflLayout from "./layout";

vi.mock("next/navigation", () => ({ usePathname: () => "/nfl/accuracy" }));

describe("NFL section layout", () => {
  it("credits nflverse on every NFL page, with a link to the data source", () => {
    render(<NflLayout><p>child</p></NflLayout>);
    expect(screen.getByText("child")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /nflverse/i });
    expect(link).toHaveAttribute("href", "https://github.com/nflverse/nfldata");
    expect(screen.getByRole("contentinfo")).toHaveTextContent(/schedule.*results.*nflverse/i);
  });

  it("has an NFL section nav to predictions and accuracy", () => {
    render(<NflLayout><p>child</p></NflLayout>);
    const nav = screen.getByRole("navigation", { name: "NFL" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Predictions" })).toHaveAttribute("href", "/nfl");
    expect(screen.getByRole("link", { name: "Accuracy" })).toHaveAttribute("href", "/nfl/accuracy");
  });
});
