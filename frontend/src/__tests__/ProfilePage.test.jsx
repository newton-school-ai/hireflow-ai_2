import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ProfilePage from "../pages/ProfilePage";
import * as apiClient from "../api/client";

// Mock the API client
vi.mock("../api/client", () => ({
  createProfile: vi.fn(),
}));

describe("ProfilePage Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all core profile inputs and mode selector", () => {
    render(<ProfilePage />);

    expect(screen.getByText(/Candidate Profile Setup/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/e\.g\. Alex Chen/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/alex\.chen@example\.com/i)).toBeInTheDocument();
    expect(screen.getByText(/Internship Mode/i)).toBeInTheDocument();
    expect(screen.getByText(/Full-time Job Mode/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save & Register Profile/i })).toBeInTheDocument();
  });

  it("allows adding and removing skills", () => {
    render(<ProfilePage />);

    const skillInput = screen.getByPlaceholderText(/Type a skill/i);
    const addSkillBtn = screen.getByRole("button", { name: /Add Skill/i });

    // Add new skill
    fireEvent.change(skillInput, { target: { value: "PyTorch" } });
    fireEvent.click(addSkillBtn);

    expect(screen.getByText("PyTorch")).toBeInTheDocument();
  });

  it("submits the form successfully and displays confirmation banner", async () => {
    apiClient.createProfile.mockResolvedValueOnce({
      id: "usr-12345-uuid",
      name: "Alex Chen",
      email: "alex@example.com",
      mode: "internship",
      weekly_quota: 5,
    });

    render(<ProfilePage />);

    const nameInput = screen.getByPlaceholderText(/e\.g\. Alex Chen/i);
    const emailInput = screen.getByPlaceholderText(/alex\.chen@example\.com/i);
    const submitBtn = screen.getByRole("button", { name: /Save & Register Profile/i });

    fireEvent.change(nameInput, { target: { value: "Alex Chen" } });
    fireEvent.change(emailInput, { target: { value: "alex@example.com" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(apiClient.createProfile).toHaveBeenCalledTimes(1);
      expect(screen.getByText(/Profile Created Successfully!/i)).toBeInTheDocument();
      expect(screen.getByText("usr-12345-uuid")).toBeInTheDocument();
    });
  });

  it("handles and displays error message when API call fails", async () => {
    apiClient.createProfile.mockRejectedValueOnce(
      new Error("Email already registered")
    );

    render(<ProfilePage />);

    const nameInput = screen.getByPlaceholderText(/e\.g\. Alex Chen/i);
    const emailInput = screen.getByPlaceholderText(/alex\.chen@example\.com/i);
    const submitBtn = screen.getByRole("button", { name: /Save & Register Profile/i });

    fireEvent.change(nameInput, { target: { value: "Alex Chen" } });
    fireEvent.change(emailInput, { target: { value: "alex@example.com" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/Email already registered/i)).toBeInTheDocument();
    });
  });
});
