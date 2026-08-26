import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ApplicationsPage from "../pages/ApplicationsPage";
import * as apiClient from "../api/client";

vi.mock("../api/client", () => ({
  getApplications: vi.fn(),
}));

describe("ApplicationsPage Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const mockApplicationsData = {
    items: [
      {
        id: "app-1",
        company_name: "Google AI",
        role_title: "AI Engineer",
        status: "applied",
        applied_at: "2026-08-20T10:00:00Z",
        match_score: 95,
        resume_path: "data/resumes/google.pdf",
        application_url: "https://google.com/careers/1",
      },
      {
        id: "app-2",
        company_name: "Amazon AWS",
        role_title: "Cloud Developer",
        status: "needs_action",
        applied_at: null,
        created_at: "2026-08-21T10:00:00Z",
        match_score: 82,
        failure_reason: "CAPTCHA detected",
        manual_application_url: "https://amazon.jobs/apply/2",
        application_url: "https://amazon.jobs/apply/2",
        resume_path: "data/resumes/amazon.pdf",
      },
      {
        id: "app-3",
        company_name: "Startup XYZ",
        role_title: "Fullstack Intern",
        status: "failed",
        applied_at: null,
        created_at: "2026-08-22T10:00:00Z",
        match_score: 70,
        failure_reason: "Job posting expired",
        application_url: "https://startup.xyz/apply",
        resume_path: "data/resumes/startup.pdf",
      },
    ],
  };

  it("renders applications table with status badges", async () => {
    apiClient.getApplications.mockResolvedValueOnce(mockApplicationsData);

    render(
      <BrowserRouter>
        <ApplicationsPage />
      </BrowserRouter>
    );

    await waitFor(() => {
      expect(screen.getByText(/Application Status Tracker/i)).toBeInTheDocument();
      expect(screen.getByText("Google AI")).toBeInTheDocument();
      expect(screen.getByText("Amazon AWS")).toBeInTheDocument();
      expect(screen.getByText("Startup XYZ")).toBeInTheDocument();
      expect(screen.getAllByText("Applied").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("Needs Action").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("Failed").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("displays manual application URL link for needs_action items", async () => {
    apiClient.getApplications.mockResolvedValueOnce(mockApplicationsData);

    render(
      <BrowserRouter>
        <ApplicationsPage />
      </BrowserRouter>
    );

    await waitFor(() => {
      expect(screen.getByText(/Complete Application Now/i)).toBeInTheDocument();
      const link = screen.getByRole("link", { name: /Complete Application Now/i });
      expect(link).toHaveAttribute("href", "https://amazon.jobs/apply/2");
    });
  });

  it("filters applications when status tab is selected", async () => {
    apiClient.getApplications.mockResolvedValue(mockApplicationsData);

    render(
      <BrowserRouter>
        <ApplicationsPage />
      </BrowserRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Google AI")).toBeInTheDocument();
    });

    // Click Needs Action filter tab
    const needsActionTab = screen.getByRole("button", { name: /^Needs Action$/i });
    fireEvent.click(needsActionTab);

    await waitFor(() => {
      expect(screen.getByText("Amazon AWS")).toBeInTheDocument();
      expect(screen.queryByText("Google AI")).not.toBeInTheDocument();
    });
  });
});
