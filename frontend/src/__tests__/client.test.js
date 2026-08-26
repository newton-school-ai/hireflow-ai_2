import { describe, it, expect, vi, beforeEach } from "vitest";
import axios from "axios";
import { apiClient, createProfile, getProfile } from "../api/client";

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

  it("createProfile sends multipart header when isFormData is true", async () => {
    const postSpy = vi.spyOn(apiClient, "post").mockResolvedValueOnce({
      data: { id: "user-123" },
    });

    const formData = new FormData();
    formData.append("mode", "internship");

    const result = await createProfile(formData, true);

    expect(postSpy).toHaveBeenCalledWith("/profile", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    expect(result.id).toBe("user-123");
  });

  it("getProfile calls get with userId", async () => {
    const getSpy = vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: { id: "user-456", name: "Sam" },
    });

    const result = await getProfile("user-456");

    expect(getSpy).toHaveBeenCalledWith("/profile/user-456");
    expect(result.name).toBe("Sam");
  });
});
