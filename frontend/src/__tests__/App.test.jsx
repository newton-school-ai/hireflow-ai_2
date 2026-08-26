import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import App from "../App";

describe("App Routing and Navigation", () => {
  it("renders Profile Setup page on default route '/'", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByText(/Candidate Profile Setup/i)).toBeInTheDocument();
  });

  it("renders Weekly Plan page on '/weekly-plan'", () => {
    render(
      <MemoryRouter initialEntries={["/weekly-plan"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByText(/Weekly Plan & Opportunity Batch/i)).toBeInTheDocument();
  });

  it("renders Applications page on '/applications'", () => {
    render(
      <MemoryRouter initialEntries={["/applications"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByText(/Application Status & Audit Log/i)).toBeInTheDocument();
  });

  it("renders Prep Guide page on '/prep-guide/:id'", () => {
    render(
      <MemoryRouter initialEntries={["/prep-guide/opp-123"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByText(/AI Interview Prep Guide/i)).toBeInTheDocument();
    expect(screen.getByText(/opp-123/i)).toBeInTheDocument();
  });

  it("renders Resumes page on '/resumes'", () => {
    render(
      <MemoryRouter initialEntries={["/resumes"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByText(/Tailored Resume Library/i)).toBeInTheDocument();
  });
});
