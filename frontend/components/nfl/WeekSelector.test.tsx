import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WeekSelector from "./WeekSelector";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

beforeEach(() => push.mockClear());

const SEASON_2025 = [
  { week: 1, label: "Week 1" },
  { week: 18, label: "Week 18" },
  { week: 19, label: "Wild Card" },
  { week: 22, label: "Super Bowl" },
];

describe("WeekSelector (spec 5.4)", () => {
  it("labels 2025 week 19 'Wild Card' and week 18 'Week 18'", () => {
    render(<WeekSelector season={2025} current={19} weeks={SEASON_2025} />);
    expect(screen.getByRole("option", { name: "Wild Card" })).toHaveValue("19");
    expect(screen.getByRole("option", { name: "Week 18" })).toHaveValue("18");
    expect(screen.getAllByRole("option")).toHaveLength(4);
  });

  it("uses the API label verbatim, never its own week-number mapping", () => {
    // 2020: the Wild Card round was week 18.
    render(<WeekSelector season={2020} current={18} weeks={[{ week: 18, label: "Wild Card" },
                                                            { week: 19, label: "Divisional" }]} />);
    expect(screen.getByRole("option", { name: "Wild Card" })).toHaveValue("18");
    expect(screen.queryByRole("option", { name: "Week 18" })).not.toBeInTheDocument();
  });

  it("is a labelled control reflecting the current week", () => {
    render(<WeekSelector season={2025} current={19} weeks={SEASON_2025} />);
    expect(screen.getByLabelText("Week:")).toHaveValue("19");
  });

  it("navigates to the chosen week of the same season", async () => {
    const user = userEvent.setup();
    render(<WeekSelector season={2025} current={19} weeks={SEASON_2025} />);
    await user.selectOptions(screen.getByRole("combobox"), "22");
    expect(push).toHaveBeenCalledWith("/nfl/predictions/2025/22");
  });
});
