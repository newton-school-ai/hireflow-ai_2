import React, { useState } from "react";
import { 
  User, 
  Mail, 
  Upload, 
  CheckCircle2, 
  AlertCircle, 
  Loader2, 
  DollarSign, 
  MapPin, 
  Target, 
  Sliders, 
  FileText,
  X,
  Plus
} from "lucide-react";
import ModeSelector from "../components/ModeSelector";
import { createProfile } from "../api/client";

export default function ProfilePage() {
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    mode: "internship",
    weekly_quota: 5,
    confirmation_mode: "batch",
    skills: ["Python", "React", "FastAPI"],
    target_roles: ["Software Engineer Intern", "Full Stack Developer"],
    preferred_locations: ["Remote", "Bengaluru"],
    min_stipend: 25000,
    min_salary: 800000,
  });

  const [skillInput, setSkillInput] = useState("");
  const [roleInput, setRoleInput] = useState("");
  const [locationInput, setLocationInput] = useState("");
  
  const [resumeFile, setResumeFile] = useState(null);
  const [usePdfUpload, setUsePdfUpload] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [successResult, setSuccessResult] = useState(null);

  const handleInputChange = (e) => {
    const { name, value, type } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: type === "number" ? (value === "" ? "" : Number(value)) : value,
    }));
  };

  const handleAddTag = (field, value, setter) => {
    const trimmed = value.trim();
    if (trimmed && !formData[field].includes(trimmed)) {
      setFormData((prev) => ({
        ...prev,
        [field]: [...prev[field], trimmed],
      }));
      setter("");
    }
  };

  const handleRemoveTag = (field, tagToRemove) => {
    setFormData((prev) => ({
      ...prev,
      [field]: prev[field].filter((item) => item !== tagToRemove),
    }));
  };

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      if (file.type !== "application/pdf") {
        setError("Please upload a valid PDF document.");
        return;
      }
      setResumeFile(file);
      setError(null);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccessResult(null);

    try {
      let result;
      if (usePdfUpload && resumeFile) {
        const payload = new FormData();
        payload.append("file", resumeFile);
        payload.append("mode", formData.mode);
        payload.append("weekly_quota", formData.weekly_quota);
        payload.append("confirmation_mode", formData.confirmation_mode);
        result = await createProfile(payload, true);
      } else {
        const payload = {
          ...formData,
          weekly_quota: Number(formData.weekly_quota),
          min_stipend: formData.mode === "internship" ? Number(formData.min_stipend) || null : null,
          min_salary: formData.mode === "job" ? Number(formData.min_salary) || null : null,
        };
        result = await createProfile(payload, false);
      }

      setSuccessResult(result);
    } catch (err) {
      setError(err.message || "Failed to create profile. Please check your details.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
      {/* Page Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">
          Candidate Profile Setup
        </h1>
        <p className="text-slate-600 mt-1.5 text-base">
          Configure your preferences, skills, and target opportunities for the autonomous application engine.
        </p>
      </div>

      {/* Success Banner */}
      {successResult && (
        <div className="mb-8 p-6 rounded-2xl bg-emerald-50 border border-emerald-200 shadow-sm animate-fade-in">
          <div className="flex items-start gap-4">
            <div className="p-2 bg-emerald-500 text-white rounded-xl">
              <CheckCircle2 className="w-6 h-6" />
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-bold text-emerald-900">
                Profile Created Successfully!
              </h3>
              <p className="text-emerald-700 text-sm mt-1">
                Your profile is registered and ready for weekly quota matching.
              </p>
              <div className="mt-4 p-3 bg-white/80 rounded-xl border border-emerald-100 text-xs font-mono text-slate-700 flex flex-wrap gap-x-6 gap-y-2">
                <div>
                  <span className="font-semibold text-slate-500">User ID:</span>{" "}
                  <span className="text-emerald-700 font-bold">{successResult.id}</span>
                </div>
                <div>
                  <span className="font-semibold text-slate-500">Name:</span> {successResult.name}
                </div>
                <div>
                  <span className="font-semibold text-slate-500">Mode:</span>{" "}
                  <span className="capitalize font-semibold">{successResult.mode}</span>
                </div>
                <div>
                  <span className="font-semibold text-slate-500">Weekly Quota:</span> {successResult.weekly_quota} applications/week
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Error Alert */}
      {error && (
        <div className="mb-8 p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-600 mt-0.5 shrink-0" />
          <div className="text-sm font-medium">{error}</div>
        </div>
      )}

      {/* Profile Form */}
      <form onSubmit={handleSubmit} className="space-y-8 bg-white p-6 sm:p-8 rounded-2xl border border-slate-200 shadow-sm">
        {/* Section 1: Mode Selection */}
        <section>
          <ModeSelector
            mode={formData.mode}
            onChange={(newMode) => setFormData((prev) => ({ ...prev, mode: newMode }))}
            disabled={loading}
          />
        </section>

        <hr className="border-slate-100" />

        {/* Section 2: Input Method Toggle */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold text-slate-900">Onboarding Method</h2>
            <div className="inline-flex rounded-lg border border-slate-200 p-1 bg-slate-50">
              <button
                type="button"
                onClick={() => setUsePdfUpload(false)}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                  !usePdfUpload ? "bg-white text-slate-900 shadow-xs" : "text-slate-500 hover:text-slate-900"
                }`}
              >
                Manual Details
              </button>
              <button
                type="button"
                onClick={() => setUsePdfUpload(true)}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                  usePdfUpload ? "bg-white text-slate-900 shadow-xs" : "text-slate-500 hover:text-slate-900"
                }`}
              >
                Resume PDF Upload
              </button>
            </div>
          </div>

          {usePdfUpload ? (
            /* PDF Upload Box */
            <div className="mt-4">
              <label
                htmlFor="resume-upload"
                className="border-2 border-dashed border-slate-300 hover:border-sky-500 bg-slate-50/50 hover:bg-sky-50/20 rounded-2xl p-8 flex flex-col items-center justify-center cursor-pointer transition-colors text-center"
              >
                <div className="p-3 bg-sky-100 text-sky-600 rounded-full mb-3">
                  <Upload className="w-6 h-6" />
                </div>
                <span className="font-semibold text-slate-800 text-sm">
                  {resumeFile ? resumeFile.name : "Click or drag your Resume PDF here"}
                </span>
                <span className="text-xs text-slate-500 mt-1">
                  PDF format required. The LLM extraction pipeline will auto-fill your master profile.
                </span>
                <input
                  id="resume-upload"
                  type="file"
                  accept="application/pdf"
                  onChange={handleFileChange}
                  className="hidden"
                />
              </label>
              {resumeFile && (
                <div className="mt-3 flex items-center justify-between p-3 rounded-lg bg-slate-100 text-xs text-slate-700">
                  <span className="flex items-center gap-2 font-medium">
                    <FileText className="w-4 h-4 text-sky-600" />
                    {resumeFile.name} ({(resumeFile.size / 1024).toFixed(1)} KB)
                  </span>
                  <button
                    type="button"
                    onClick={() => setResumeFile(null)}
                    className="text-slate-400 hover:text-rose-500"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          ) : (
            /* Manual Personal Details */
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                  Full Name <span className="text-rose-500">*</span>
                </label>
                <div className="relative">
                  <User className="w-4 h-4 text-slate-400 absolute left-3 top-3.5" />
                  <input
                    type="text"
                    name="name"
                    required
                    value={formData.name}
                    onChange={handleInputChange}
                    placeholder="e.g. Alex Chen"
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                  Email Address <span className="text-rose-500">*</span>
                </label>
                <div className="relative">
                  <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-3.5" />
                  <input
                    type="email"
                    name="email"
                    required
                    value={formData.email}
                    onChange={handleInputChange}
                    placeholder="alex.chen@example.com"
                    className="w-full pl-9 pr-3 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 text-sm"
                  />
                </div>
              </div>
            </div>
          )}
        </section>

        {!usePdfUpload && (
          <>
            <hr className="border-slate-100" />

            {/* Section 3: Skills */}
            <section>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                Technical Skills & Tools
              </label>
              <div className="flex gap-2 mb-2.5">
                <input
                  type="text"
                  value={skillInput}
                  onChange={(e) => setSkillInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddTag("skills", skillInput, setSkillInput);
                    }
                  }}
                  placeholder="Type a skill (e.g. Python, Docker, PyTorch) and press Enter"
                  className="flex-1 px-3.5 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 text-sm"
                />
                <button
                  type="button"
                  aria-label="Add Skill"
                  onClick={() => handleAddTag("skills", skillInput, setSkillInput)}
                  className="px-4 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold rounded-xl text-sm transition-colors flex items-center gap-1.5"
                >
                  <Plus className="w-4 h-4" /> Add Skill
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {formData.skills.map((skill) => (
                  <span
                    key={skill}
                    className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-sky-50 border border-sky-200/60 text-sky-800 text-xs font-medium"
                  >
                    {skill}
                    <button
                      type="button"
                      onClick={() => handleRemoveTag("skills", skill)}
                      className="text-sky-400 hover:text-sky-700"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </span>
                ))}
              </div>
            </section>

            {/* Section 4: Target Roles & Locations */}
            <section className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {/* Target Roles */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                  <Target className="w-4 h-4 text-slate-400" /> Target Roles
                </label>
                <div className="flex gap-2 mb-2">
                  <input
                    type="text"
                    value={roleInput}
                    onChange={(e) => setRoleInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddTag("target_roles", roleInput, setRoleInput);
                      }
                    }}
                    placeholder="e.g. Backend Engineer"
                    className="flex-1 px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none focus:border-sky-500"
                  />
                  <button
                    type="button"
                    aria-label="Add Role"
                    onClick={() => handleAddTag("target_roles", roleInput, setRoleInput)}
                    className="px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold"
                  >
                    Add
                  </button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {formData.target_roles.map((role) => (
                    <span
                      key={role}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-100 text-slate-700 text-xs font-medium"
                    >
                      {role}
                      <button
                        type="button"
                        onClick={() => handleRemoveTag("target_roles", role)}
                        className="text-slate-400 hover:text-slate-600"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              {/* Preferred Locations */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                  <MapPin className="w-4 h-4 text-slate-400" /> Locations
                </label>
                <div className="flex gap-2 mb-2">
                  <input
                    type="text"
                    value={locationInput}
                    onChange={(e) => setLocationInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddTag("preferred_locations", locationInput, setLocationInput);
                      }
                    }}
                    placeholder="e.g. Remote, Mumbai"
                    className="flex-1 px-3 py-2 rounded-xl border border-slate-200 text-sm focus:outline-none focus:border-sky-500"
                  />
                  <button
                    type="button"
                    aria-label="Add Location"
                    onClick={() => handleAddTag("preferred_locations", locationInput, setLocationInput)}
                    className="px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-semibold"
                  >
                    Add
                  </button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {formData.preferred_locations.map((loc) => (
                    <span
                      key={loc}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-100 text-slate-700 text-xs font-medium"
                    >
                      {loc}
                      <button
                        type="button"
                        onClick={() => handleRemoveTag("preferred_locations", loc)}
                        className="text-slate-400 hover:text-slate-600"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            </section>

            <hr className="border-slate-100" />

            {/* Section 5: Quota & Compensation Filters */}
            <section className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {/* Weekly Quota */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                  <Sliders className="w-4 h-4 text-slate-400" /> Weekly Quota (Applications/Week)
                </label>
                <input
                  type="number"
                  name="weekly_quota"
                  min="1"
                  max="50"
                  required
                  value={formData.weekly_quota}
                  onChange={handleInputChange}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:border-sky-500 text-sm"
                />
                <p className="text-xs text-slate-400 mt-1">Recommended: 5 to 15 per week</p>
              </div>

              {/* Compensation Filter based on Mode */}
              <div>
                {formData.mode === "internship" ? (
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                      <DollarSign className="w-4 h-4 text-slate-400" /> Minimum Monthly Stipend (₹/mo)
                    </label>
                    <input
                      type="number"
                      name="min_stipend"
                      step="5000"
                      value={formData.min_stipend}
                      onChange={handleInputChange}
                      placeholder="e.g. 20000"
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:border-sky-500 text-sm"
                    />
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                      <DollarSign className="w-4 h-4 text-slate-400" /> Minimum Annual Salary (₹/yr)
                    </label>
                    <input
                      type="number"
                      name="min_salary"
                      step="50000"
                      value={formData.min_salary}
                      onChange={handleInputChange}
                      placeholder="e.g. 600000"
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:border-sky-500 text-sm"
                    />
                  </div>
                )}
              </div>
            </section>
          </>
        )}

        {/* Action Button */}
        <div className="pt-4 flex justify-end">
          <button
            type="submit"
            disabled={loading || (usePdfUpload && !resumeFile)}
            className="w-full sm:w-auto px-8 py-3 bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-700 hover:to-indigo-700 text-white font-bold rounded-xl shadow-md shadow-sky-500/20 transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Saving Profile...</span>
              </>
            ) : (
              <span>Save & Register Profile</span>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
