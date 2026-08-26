import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

// Response interceptor to normalize error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    let message = "An unexpected error occurred. Please try again.";

    if (error.response) {
      const { status, data } = error.response;
      if (typeof data?.detail === "string") {
        message = data.detail;
      } else if (Array.isArray(data?.detail)) {
        message = data.detail.map((err) => `${err.loc?.join(".") || "field"}: ${err.msg}`).join(", ");
      } else if (data?.message) {
        message = data.message;
      } else if (status >= 500) {
        message = "Server error occurred. The backend might be experiencing issues.";
      } else if (status === 404) {
        message = "Resource not found.";
      } else if (status === 400) {
        message = data?.detail || "Invalid request data. Please check your inputs.";
      } else if (status === 409) {
        message = "A conflict occurred (e.g. email already registered).";
      }
    } else if (error.request) {
      message = "Network error: Unable to connect to the HireFlow API server.";
    }

    const enhancedError = new Error(message);
    enhancedError.status = error.response?.status;
    enhancedError.originalError = error;
    return Promise.reject(enhancedError);
  }
);

/**
 * Creates or updates a user profile via JSON or Multipart PDF upload
 */
export async function createProfile(profileData, isFormData = false) {
  const config = isFormData
    ? { headers: { "Content-Type": "multipart/form-data" } }
    : {};
  const response = await apiClient.post("/profile", profileData, config);
  return response.data;
}

/**
 * Retrieves a user profile by ID
 */
export async function getProfile(userId) {
  const response = await apiClient.get(`/profile/${userId}`);
  return response.data;
}

/**
 * Retrieves the weekly application plan for a target user
 */
export async function getWeeklyPlan(userId, index = 0) {
  const response = await apiClient.get(`/weekly-plan/${userId}`, {
    params: { index },
  });
  return response.data;
}

/**
 * Swaps a selected job in the user's weekly plan with an alternative
 */
export async function swapJob(userId, removeJobId, addJobId) {
  const response = await apiClient.post(`/weekly-plan/${userId}/swap`, {
    remove_job_id: removeJobId,
    add_job_id: addJobId,
  });
  return response.data;
}

/**
 * Confirms the user's weekly plan, moving status to 'confirmed'
 */
export async function confirmWeeklyPlan(userId, payload = null) {
  const response = await apiClient.post(`/weekly-plan/${userId}/confirm`, payload || {});
  return response.data;
}

/**
 * Retrieves paginated applications with status and job metadata
 */
export async function getApplications(userId, status = null, page = 1, limit = 50) {
  const params = { page, limit };
  if (status && status !== "all") {
    params.status = status;
  }
  const response = await apiClient.get(`/applications/${userId}`, { params });
  return response.data;
}

export default apiClient;
