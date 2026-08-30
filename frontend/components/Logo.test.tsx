import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import Logo from "./Logo";

describe("Logo", () => {
  it("renders the wordmark and a decorative svg at the default size", () => {
    const { container } = render(<Logo />);
    expect(screen.getByText("PREDICTOR")).toBeInTheDocument();
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "36");
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });

  it("honours a custom size", () => {
    const { container } = render(<Logo size={48} />);
    expect(container.querySelector("svg")).toHaveAttribute("height", "48");
  });
});
