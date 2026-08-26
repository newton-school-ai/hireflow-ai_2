import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import WeeklyPlanPage from "../pages/WeeklyPlanPage";
import * as apiClient from "../api/client";

vi.mock("../api/client", () => ({
  getWeeklyPlan: vi.fn(),
  swapJob: vi.fn(),
  confirmWeeklyPlan: vi.fn(),
}));

describe("WeeklyPlanPage Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const mockPlanData = {
    user_id: "user-123",
    status: "planned",
    weekly_quota: 2,
    selected_jobs: [
      {
        id: "job-1",
        job_id: "job-1",
        company_name: "Meta AI",
        role_title: "GenAI Engineer",
        match_score: 95,
        location: "Menlo Park, CA",
        matched_skills: ["PyTorch", "LLMs"],
        skill_gaps: ["C++"],
        tailored_summary: "Passionate AI engineer.",
      },
      {
        id: "job-2",
        job_id: "job-2",
        company_name: "OpenAI Labs",
        role_title: "Research Engineer",
        match_score: 90,
        location: "San Francisco, CA",
        matched_skills: ["Python", "Transformers"],
        skill_gaps: ["CUDA"],
        tailored_summary: "Researcher in generative modeling.",
      },
    ],
    alternative_jobs: [
      {
        id: "job-3",
        job_id: "job-3",
        company_name: "DeepMind",
        role_title: "ML Specialist",
        match_score: 85,
        location: "London, UK",
        matched_skills: ["JAX"],
        skill_gaps: ["RL"],
        tailored_summary: "Reinforcement learning enthusiast.",
      },
    ],
  };

  it("renders weekly plan header, job cards, and quota indicator", async () => {
    apiClient.getWeeklyPlan.mockResolvedValueOnce(mockPlanData);

    render(
      <BrowserRouter>
        <WeeklyPlanPage />
      </BrowserRouter>
    );

    await waitFor(() => {
      expect(screen.getByText(/Weekly Application Plan/i)).toBeInTheDocument();
      expect(screen.getByText("Meta AI")).toBeInTheDocument();
      expect(screen.getByText("OpenAI Labs")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Confirm and Apply/i })).toBeInTheDocument();
    });
  });

  it("calls confirmWeeklyPlan when 'Confirm and Apply' is clicked", async () => {
    apiClient.getWeeklyPlan.mockResolvedValueOnce(mockPlanData);
    apiClient.confirmWeeklyPlan.mockResolvedValueOnce({
      user_id: "user-123",
      status: "confirmed",
    });

    render(
      <BrowserRouter>
        <WeeklyPlanPage />
      </BrowserRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Meta AI")).toBeInTheDocument();
    });

    const confirmBtn = screen.getByRole("button", { name: /Confirm and Apply/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(apiClient.confirmWeeklyPlan).toHaveBeenCalledTimes(1);
      expect(screen.getByText(/Weekly Plan Confirmed & Dispatched!/i)).toBeInTheDocument();
    });
  });

  it("allows removing a job and swapping with an alternative", async () => {
    apiClient.getWeeklyPlan.mockResolvedValueOnce(mockPlanData);
    apiClient.swapJob.mockResolvedValueOnce({});

    render(
      <BrowserRouter>
        <WeeklyPlanPage />
      </BrowserRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Meta AI")).toBeInTheDocument();
    });

    // Remove first job
    const removeButtons = screen.getAllByTitle(/Remove and replace/i);
    fireEvent.click(removeButtons[0]);

    await waitFor(() => {
      // DeepMind was in alternative_jobs, so it should replace Meta AI
      expect(screen.getByText("DeepMind")).toBeInTheDocument();
    });
  });
});
