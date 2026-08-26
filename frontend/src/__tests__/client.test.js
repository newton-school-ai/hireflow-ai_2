import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiClient, createProfile, getProfile, getWeeklyPlan, swapJob, confirmWeeklyPlan, getApplications } from "../api/client";

describe("API Client & Methods", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("createProfile calls post with json data by default", async () => {
    const postSpy = vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: { id: "user-123", name: "Alex" },
    });

    const result = await createProfile({ name: "Alex", email: "alex@test.com" }, false);

    expect(postSpy).toHaveBeenCalledWith(
      "/profile",
      { name: "Alex", email: "alex@test.com" },
      {}
    );
    expect(result).toEqual({ id: "user-123", name: "Alex" });
  });

  it("getWeeklyPlan calls get with userId", async () => {
    const getSpy = vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: { user_id: "user-123", selected_jobs: [] },
    });

    const result = await getWeeklyPlan("user-123");

    expect(getSpy).toHaveBeenCalledWith("/weekly-plan/user-123", { params: { index: 0 } });
    expect(result.user_id).toBe("user-123");
  });

  it("swapJob calls post to swap endpoint", async () => {
    const postSpy = vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: { status: "swapped" },
    });

    const result = await swapJob("user-123", "job-1", "job-2");

    expect(postSpy).toHaveBeenCalledWith("/weekly-plan/user-123/swap", {
      remove_job_id: "job-1",
      add_job_id: "job-2",
    });
    expect(result.status).toBe("swapped");
  });

  it("confirmWeeklyPlan calls post to confirm endpoint", async () => {
    const postSpy = vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: { status: "confirmed" },
    });

    const result = await confirmWeeklyPlan("user-123", { confirmed_job_ids: ["job-1"] });

    expect(postSpy).toHaveBeenCalledWith("/weekly-plan/user-123/confirm", {
      confirmed_job_ids: ["job-1"],
    });
    expect(result.status).toBe("confirmed");
  });

  it("getApplications calls get with userId and query params", async () => {
    const getSpy = vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: { items: [] },
    });

    const result = await getApplications("user-123", "needs_action", 1, 20);

    expect(getSpy).toHaveBeenCalledWith("/applications/user-123", {
      params: { page: 1, limit: 20, status: "needs_action" },
    });
    expect(result.items).toEqual([]);
  });
});
