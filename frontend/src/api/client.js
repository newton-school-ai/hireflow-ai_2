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
        // Pydantic validation error array
        message = data.detail.map((err) => `${err.loc?.join(".") || "field"}: ${err.msg}`).join(", ");
      } else if (data?.message) {
        message = data.message;
      } else if (status >= 500) {
        message = "Server error occurred. The backend might be experiencing issues.";
      } else if (status === 404) {
        message = "Resource not found.";
      } else if (status === 400) {
        message = "Invalid request data. Please check your inputs.";
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
 * @param {Object|FormData} profileData
 * @param {boolean} isFormData
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
 * @param {string} userId
 */
export async function getProfile(userId) {
  const response = await apiClient.get(`/profile/${userId}`);
  return response.data;
}

export default apiClient;
