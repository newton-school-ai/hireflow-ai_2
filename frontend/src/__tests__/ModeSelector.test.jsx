import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ModeSelector from "../components/ModeSelector";

describe("ModeSelector Component", () => {
  it("renders both internship and job mode options", () => {
    render(<ModeSelector mode="internship" onChange={vi.fn()} />);

    expect(screen.getByText(/Internship Mode/i)).toBeInTheDocument();
    expect(screen.getByText(/Full-time Job Mode/i)).toBeInTheDocument();
    expect(screen.getByText(/Active/i)).toBeInTheDocument();
  });

  it("calls onChange with 'job' when Full-time Job button is clicked", () => {
    const handleChange = vi.fn();
    render(<ModeSelector mode="internship" onChange={handleChange} />);

    const jobButton = screen.getByRole("button", { name: /Full-time Job Mode/i });
    fireEvent.click(jobButton);

    expect(handleChange).toHaveBeenCalledTimes(1);
    expect(handleChange).toHaveBeenCalledWith("job");
  });

  it("calls onChange with 'internship' when Internship button is clicked", () => {
    const handleChange = vi.fn();
    render(<ModeSelector mode="job" onChange={handleChange} />);

    const internshipButton = screen.getByRole("button", { name: /Internship Mode/i });
    fireEvent.click(internshipButton);

    expect(handleChange).toHaveBeenCalledTimes(1);
    expect(handleChange).toHaveBeenCalledWith("internship");
  });

  it("disables both buttons when disabled prop is true", () => {
    render(<ModeSelector mode="internship" onChange={vi.fn()} disabled={true} />);

    const buttons = screen.getAllByRole("button");
    buttons.forEach((btn) => {
      expect(btn).toBeDisabled();
    });
  });
});
