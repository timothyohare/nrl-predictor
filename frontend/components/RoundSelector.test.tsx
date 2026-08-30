import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RoundSelector from "./RoundSelector";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

beforeEach(() => push.mockClear());

describe("RoundSelector", () => {
  it("renders all 27 rounds plus the four finals options", () => {
    render(<RoundSelector current={1} />);
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(31);
    expect(screen.getByRole("option", { name: "Round 1" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Round 27" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Grand Final" })).toBeInTheDocument();
  });

  it("reflects the current round as the selected value", () => {
    render(<RoundSelector current={9} />);
    expect(screen.getByRole("combobox")).toHaveValue("9");
  });

  it("navigates to the chosen round on change", async () => {
    const user = userEvent.setup();
    render(<RoundSelector current={1} />);
    await user.selectOptions(screen.getByRole("combobox"), "14");
    expect(push).toHaveBeenCalledWith("/predictions/14");
  });

  it("navigates to a finals value like any other round", async () => {
    const user = userEvent.setup();
    render(<RoundSelector current={1} />);
    await user.selectOptions(screen.getByRole("combobox"), "31");
    expect(push).toHaveBeenCalledWith("/predictions/31");
  });
});
