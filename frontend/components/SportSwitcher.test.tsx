import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import SportSwitcher from "./SportSwitcher";

let pathname = "/";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

beforeEach(() => {
  pathname = "/";
});

function active() {
  return screen.getAllByRole("link").filter((a) => a.getAttribute("aria-current") === "page")
    .map((a) => a.textContent);
}

describe("SportSwitcher (spec 5.5)", () => {
  it("links NRL to /predictions/current and NFL to /nfl", () => {
    render(<SportSwitcher />);
    expect(screen.getByRole("link", { name: "NRL" })).toHaveAttribute("href", "/predictions/current");
    expect(screen.getByRole("link", { name: "NFL" })).toHaveAttribute("href", "/nfl");
  });

  it("is a labelled navigation landmark", () => {
    render(<SportSwitcher />);
    expect(screen.getByRole("navigation", { name: "Sport" })).toBeInTheDocument();
  });

  it.each(["/nfl", "/nfl/", "/nfl/predictions/2026/8", "/nfl/accuracy"])(
    "marks NFL active on %s", (path) => {
      pathname = path;
      render(<SportSwitcher />);
      expect(active()).toEqual(["NFL"]);
    },
  );

  it.each(["/", "/predictions/12", "/accuracy", "/tournament", "/how-it-works", "/nflx", "/predictions/nfl"])(
    "marks NRL active on %s", (path) => {
      pathname = path;
      render(<SportSwitcher />);
      expect(active()).toEqual(["NRL"]);
    },
  );

  it("treats a missing pathname as NRL", () => {
    pathname = null as unknown as string;
    render(<SportSwitcher />);
    expect(active()).toEqual(["NRL"]);
  });
});
