import React, { useEffect } from "react";
import { X, FileText, ExternalLink, CheckCircle, Sparkles } from "lucide-react";

export default function ResumePreview({ isOpen, onClose, job, user }) {
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") onClose();
    };
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !job) return null;

  const candidateName = user?.name || "Candidate";
  const resumeSummary = job.tailored_summary || 
    `Results-driven software engineer specialized in ${job.skills?.slice(0, 3).join(", ") || "full-stack development"}. Proven background building production-ready applications with strong focus on performance and clean architecture.`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-fade-in">
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden animate-scale-up">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/70">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-sky-100 text-sky-600">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-base text-slate-900">Tailored Resume Preview</h3>
              <p className="text-xs text-slate-500">
                Customized for <span className="font-semibold text-slate-700">{job.company_name}</span> — {job.role_title}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close modal"
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body: Resume Document View */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Candidate Header */}
          <div className="text-center pb-4 border-b border-slate-100">
            <h2 className="text-xl font-bold text-slate-900">{candidateName}</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {user?.email || "candidate@hireflow.ai"} • Mode: <span className="capitalize">{user?.mode || "Internship"}</span>
            </p>
          </div>

          {/* AI Tailoring Badge */}
          <div className="p-3 rounded-xl bg-sky-50/80 border border-sky-200/60 flex items-start gap-2.5">
            <Sparkles className="w-4 h-4 text-sky-600 mt-0.5 shrink-0" />
            <div className="text-xs text-sky-900">
              <span className="font-semibold">Tailoring Match:</span> Skills and project bullets reordered based on {job.company_name}'s technical requirements.
            </div>
          </div>

          {/* Professional Summary */}
          <div>
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Professional Summary</h4>
            <p className="text-xs sm:text-sm text-slate-700 leading-relaxed bg-slate-50 p-3.5 rounded-xl border border-slate-100">
              {resumeSummary}
            </p>
          </div>

          {/* Highlighted Relevant Skills */}
          <div>
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Targeted Keywords & Skills</h4>
            <div className="flex flex-wrap gap-1.5">
              {(job.matched_skills?.length ? job.matched_skills : job.skills || ["Python", "React", "SQL"]).map((skill) => (
                <span
                  key={skill}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-800 border border-emerald-200/60 text-xs font-medium"
                >
                  <CheckCircle className="w-3 h-3 text-emerald-600" /> {skill}
                </span>
              ))}
            </div>
          </div>

          {/* PDF Artifact Path / Link */}
          {job.resume_path && (
            <div className="text-xs font-mono text-slate-500 bg-slate-100 p-2.5 rounded-lg flex items-center justify-between">
              <span className="truncate">Path: {job.resume_path}</span>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-4 border-t border-slate-100 bg-slate-50 flex items-center justify-between">
          <span className="text-xs text-slate-400 font-medium">Ready for automated submission</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-semibold text-slate-700 bg-white border border-slate-200 rounded-xl hover:bg-slate-50"
            >
              Close
            </button>
            {job.application_url && (
              <a
                href={job.application_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-sky-600 hover:bg-sky-700 rounded-xl transition-colors"
              >
                View Job Posting <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
