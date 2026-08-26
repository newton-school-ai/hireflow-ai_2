import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import JobCard from "../components/JobCard";

describe("JobCard Component", () => {
  const sampleJob = {
    id: "job-1",
    company_name: "Google AI",
    role_title: "Machine Learning Intern",
    match_score: 92,
    location: "Mountain View, CA",
    stipend: "$50/hr",
    skill_gaps: ["JAX", "TPU Tuning", "Distributed Training"],
    tailored_summary: "Expertise in deep learning models.",
  };

  it("renders job company, role, match score, and skill gaps", () => {
    render(
      <BrowserRouter>
        <JobCard job={sampleJob} rank={1} onPreviewResume={vi.fn()} onRemove={vi.fn()} />
      </BrowserRouter>
    );

    expect(screen.getByText("Google AI")).toBeInTheDocument();
    expect(screen.getByText("Machine Learning Intern")).toBeInTheDocument();
    expect(screen.getByText("92% Match")).toBeInTheDocument();
    expect(screen.getByText("JAX")).toBeInTheDocument();
    expect(screen.getByText("TPU Tuning")).toBeInTheDocument();
  });

  it("calls onPreviewResume when Preview Resume button is clicked", () => {
    const handlePreview = vi.fn();
    render(
      <BrowserRouter>
        <JobCard job={sampleJob} onPreviewResume={handlePreview} onRemove={vi.fn()} />
      </BrowserRouter>
    );

    const previewBtn = screen.getByRole("button", { name: /Preview Resume/i });
    fireEvent.click(previewBtn);

    expect(handlePreview).toHaveBeenCalledTimes(1);
    expect(handlePreview).toHaveBeenCalledWith(sampleJob);
  });

  it("calls onRemove when Remove button is clicked", () => {
    const handleRemove = vi.fn();
    render(
      <BrowserRouter>
        <JobCard job={sampleJob} onPreviewResume={vi.fn()} onRemove={handleRemove} canRemove={true} />
      </BrowserRouter>
    );

    const removeBtn = screen.getByTitle(/Remove and replace/i);
    fireEvent.click(removeBtn);

    expect(handleRemove).toHaveBeenCalledTimes(1);
    expect(handleRemove).toHaveBeenCalledWith(sampleJob);
  });
});
