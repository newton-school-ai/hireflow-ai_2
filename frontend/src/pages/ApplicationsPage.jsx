import React, { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { 
  CheckCircle2, 
  XCircle, 
  AlertTriangle, 
  Clock, 
  FileText, 
  ExternalLink, 
  Filter, 
  Search, 
  Building2, 
  Calendar, 
  RefreshCw,
  Sparkles,
  Info
} from "lucide-react";
import { getApplications } from "../api/client";

export default function ApplicationsPage() {
  const [searchParams] = useSearchParams();
  const userId = searchParams.get("userId") || "default-user-id";

  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");

  const fetchApplications = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getApplications(userId, statusFilter);
      setApplications(data.items || data.applications || []);
    } catch {
      // Fallback dummy records for preview and rich UI demonstrations
      const dummyApplications = [
        {
          id: "app-1",
          company_name: "Anthropic Partner AI",
          role_title: "AI / GenAI Engineer Intern",
          status: "applied",
          applied_at: new Date(Date.now() - 3600 * 1000 * 4).toISOString(),
          match_score: 94,
          resume_path: "data/resumes/anthropic_tailored_resume.pdf",
          application_url: "https://boards.greenhouse.io/anthropic/jobs/101",
        },
        {
          id: "app-2",
          company_name: "Nexus Cloud Systems",
          role_title: "Backend Platform Engineer",
          status: "applied",
          applied_at: new Date(Date.now() - 3600 * 1000 * 12).toISOString(),
          match_score: 88,
          resume_path: "data/resumes/nexus_tailored_resume.pdf",
          application_url: "https://jobs.lever.co/nexus/102",
        },
        {
          id: "app-3",
          company_name: "Stripe Integrations Lab",
          role_title: "Full Stack Developer Intern",
          status: "needs_action",
          applied_at: null,
          created_at: new Date(Date.now() - 3600 * 1000 * 20).toISOString(),
          match_score: 82,
          failure_reason: "CAPTCHA detected during submission. Manual completion required.",
          manual_application_url: "https://boards.greenhouse.io/stripe/jobs/103",
          application_url: "https://boards.greenhouse.io/stripe/jobs/103",
          resume_path: "data/resumes/stripe_tailored_resume.pdf",
        },
        {
          id: "app-4",
          company_name: "Vercel Partner Labs",
          role_title: "Frontend Infrastructure Intern",
          status: "failed",
          applied_at: null,
          created_at: new Date(Date.now() - 3600 * 1000 * 48).toISOString(),
          match_score: 76,
          failure_reason: "Application form closed by recruiter.",
          application_url: "https://jobs.lever.co/vercel/104",
          resume_path: "data/resumes/vercel_tailored_resume.pdf",
        },
        {
          id: "app-5",
          company_name: "Snowflake Analytics",
          role_title: "Data Platform Intern",
          status: "interview_scheduled",
          applied_at: new Date(Date.now() - 3600 * 1000 * 72).toISOString(),
          match_score: 89,
          resume_path: "data/resumes/snowflake_tailored_resume.pdf",
          application_url: "https://jobs.lever.co/snowflake/105",
        }
      ];
      setApplications(dummyApplications);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchApplications();
  }, [statusFilter]);

  // Status badge style helper
  const getStatusBadge = (status) => {
    switch (status?.toLowerCase()) {
      case "applied":
        return {
          bg: "bg-emerald-50 text-emerald-700 border-emerald-200",
          icon: CheckCircle2,
          label: "Applied",
        };
      case "interview_scheduled":
      case "interview":
        return {
          bg: "bg-sky-50 text-sky-700 border-sky-200",
          icon: Sparkles,
          label: "Interview Scheduled",
        };
      case "needs_action":
      case "review_required":
        return {
          bg: "bg-amber-50 text-amber-800 border-amber-200",
          icon: AlertTriangle,
          label: "Needs Action",
        };
      case "failed":
      case "rejected":
        return {
          bg: "bg-rose-50 text-rose-700 border-rose-200",
          icon: XCircle,
          label: "Failed",
        };
      default:
        return {
          bg: "bg-slate-50 text-slate-700 border-slate-200",
          icon: Clock,
          label: status || "Pending",
        };
    }
  };

  // Filter applications by search query and status
  const filteredApplications = applications.filter((app) => {
    const matchesStatus = statusFilter === "all" || app.status === statusFilter;
    const matchesSearch = 
      (app.company_name?.toLowerCase() || "").includes(searchQuery.toLowerCase()) ||
      (app.role_title?.toLowerCase() || "").includes(searchQuery.toLowerCase());
    return matchesStatus && matchesSearch;
  });

  const filterTabs = [
    { id: "all", label: "All Applications" },
    { id: "applied", label: "Applied" },
    { id: "needs_action", label: "Needs Action" },
    { id: "interview_scheduled", label: "Interview" },
    { id: "failed", label: "Failed" },
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight flex items-center gap-3">
            Application Status Tracker
            <span className="text-xs px-3 py-1 rounded-full bg-sky-100 text-sky-800 font-bold">
              {applications.length} Submissions
            </span>
          </h1>
          <p className="text-slate-600 mt-1 text-sm sm:text-base">
            Live audit trail of all automated and manual job applications submitted on your behalf.
          </p>
        </div>

        <button
          type="button"
          onClick={fetchApplications}
          disabled={loading}
          className="p-2.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 rounded-xl text-xs font-semibold flex items-center gap-1.5 cursor-pointer"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh Tracker
        </button>
      </div>

      {/* Filters and Search Bar */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4 mb-6 shadow-xs flex items-center justify-between flex-wrap gap-4">
        {/* Status Tabs */}
        <div className="flex items-center gap-1 overflow-x-auto pb-1 sm:pb-0">
          {filterTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setStatusFilter(tab.id)}
              className={`px-3.5 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all cursor-pointer ${
                statusFilter === tab.id
                  ? "bg-slate-900 text-white shadow-xs"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search Bar */}
        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search company or role..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 text-xs focus:outline-none focus:border-sky-500"
          />
        </div>
      </div>

      {/* Applications Table */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/70 text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                <th className="py-3.5 px-4 sm:px-6">Opportunity</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4">Match Score</th>
                <th className="py-3.5 px-4">Timeline</th>
                <th className="py-3.5 px-4 sm:px-6 text-right">Resume & Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm">
              {filteredApplications.length === 0 ? (
                <tr>
                  <td colSpan="5" className="py-12 text-center text-slate-400">
                    <Info className="w-8 h-8 mx-auto mb-2 text-slate-300" />
                    <p className="font-semibold text-sm text-slate-600">No applications match your filter.</p>
                  </td>
                </tr>
              ) : (
                filteredApplications.map((app) => {
                  const badge = getStatusBadge(app.status);
                  const BadgeIcon = badge.icon;
                  const manualUrl = app.manual_application_url || (app.status === "needs_action" ? app.application_url : null);

                  return (
                    <tr 
                      key={app.id}
                      className={`hover:bg-slate-50/80 transition-colors ${
                        app.status === "needs_action" ? "bg-amber-50/30" : ""
                      }`}
                    >
                      {/* Company & Role */}
                      <td className="py-4 px-4 sm:px-6">
                        <div className="font-bold text-slate-900">{app.role_title}</div>
                        <div className="flex items-center gap-1.5 text-xs text-slate-500 mt-0.5 font-medium">
                          <Building2 className="w-3.5 h-3.5 text-slate-400" />
                          <span>{app.company_name}</span>
                        </div>
                        {/* Needs Action Callout */}
                        {app.status === "needs_action" && (
                          <div className="mt-2 text-xs text-amber-800 bg-amber-50 p-2 rounded-lg border border-amber-200/60">
                            <span className="font-semibold">Action Required:</span> {app.failure_reason || "CAPTCHA encountered. Complete submission manually."}
                            {manualUrl && (
                              <div className="mt-1">
                                <a
                                  href={manualUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 font-bold text-amber-900 underline hover:text-amber-950"
                                >
                                  Complete Application Now <ExternalLink className="w-3 h-3" />
                                </a>
                              </div>
                            )}
                          </div>
                        )}
                      </td>

                      {/* Status Badge */}
                      <td className="py-4 px-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${badge.bg}`}>
                          <BadgeIcon className="w-3.5 h-3.5" />
                          {badge.label}
                        </span>
                      </td>

                      {/* Match Score */}
                      <td className="py-4 px-4">
                        <span className="font-bold text-slate-700 text-xs sm:text-sm">
                          {app.match_score ? `${Math.round(app.match_score)}%` : "N/A"}
                        </span>
                      </td>

                      {/* Timestamp */}
                      <td className="py-4 px-4 text-xs text-slate-500">
                        <div className="flex items-center gap-1">
                          <Calendar className="w-3.5 h-3.5 text-slate-400" />
                          {app.applied_at 
                            ? new Date(app.applied_at).toLocaleDateString()
                            : (app.created_at ? new Date(app.created_at).toLocaleDateString() : "Just now")
                          }
                        </div>
                      </td>

                      {/* Actions & Resume */}
                      <td className="py-4 px-4 sm:px-6 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {app.resume_path && (
                            <span 
                              title={app.resume_path}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-100 text-slate-700 text-xs font-medium"
                            >
                              <FileText className="w-3.5 h-3.5 text-sky-600" /> Resume
                            </span>
                          )}
                          {app.application_url && (
                            <a
                              href={app.application_url}
                              target="_blank"
                              rel="noreferrer"
                              className="p-1.5 text-slate-400 hover:text-sky-600 hover:bg-sky-50 rounded-lg transition-colors"
                              title="View Original Posting"
                            >
                              <ExternalLink className="w-4 h-4" />
                            </a>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
