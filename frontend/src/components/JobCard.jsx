import React from "react";
import { Link } from "react-router-dom";
import { 
  Building2, 
  MapPin, 
  DollarSign, 
  FileText, 
  BookOpen, 
  Trash2, 
  AlertTriangle,
  ArrowRight,
  Sparkles
} from "lucide-react";

export default function JobCard({ 
  job, 
  rank, 
  onPreviewResume, 
  onRemove, 
  canRemove = true 
}) {
  const matchScore = Math.round(Number(job.match_score || 0));
  const skillGaps = job.skill_gaps || [];

  // Match score color styling
  let scoreBadgeClass = "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (matchScore < 60) {
    scoreBadgeClass = "bg-rose-50 text-rose-700 border-rose-200";
  } else if (matchScore < 75) {
    scoreBadgeClass = "bg-amber-50 text-amber-700 border-amber-200";
  }

  const resumeSummary = job.tailored_summary || 
    `Tailored resume highlighting ${job.matched_skills?.slice(0, 3).join(", ") || "core technical capabilities"} for ${job.role_title}.`;

  return (
    <div className="bg-white rounded-2xl border border-slate-200 p-5 sm:p-6 shadow-xs hover:shadow-md transition-all duration-200 flex flex-col justify-between group">
      <div>
        {/* Top Header: Rank, Company, Role, Score */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-start gap-3">
            {rank && (
              <span className="w-7 h-7 rounded-lg bg-slate-900 text-white text-xs font-bold flex items-center justify-center shrink-0">
                #{rank}
              </span>
            )}
            <div>
              <h3 className="font-bold text-base sm:text-lg text-slate-900 leading-snug group-hover:text-sky-600 transition-colors">
                {job.role_title}
              </h3>
              <div className="flex items-center gap-1.5 text-xs text-slate-600 mt-0.5 font-medium">
                <Building2 className="w-3.5 h-3.5 text-slate-400" />
                <span>{job.company_name}</span>
                {job.source && (
                  <span className="ml-1 text-[10px] uppercase font-bold text-slate-400 px-1.5 py-0.2 bg-slate-100 rounded">
                    {job.source}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Match Score Badge */}
          <div className={`px-2.5 py-1 rounded-xl border text-xs font-bold flex items-center gap-1 shrink-0 ${scoreBadgeClass}`}>
            <Sparkles className="w-3.5 h-3.5" />
            <span>{matchScore}% Match</span>
          </div>
        </div>

        {/* Location & Compensation meta */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 my-3">
          {job.location && (
            <span className="flex items-center gap-1">
              <MapPin className="w-3.5 h-3.5 text-slate-400" /> {job.location}
            </span>
          )}
          {(job.stipend || job.salary) && (
            <span className="flex items-center gap-1 font-medium text-slate-700">
              <DollarSign className="w-3.5 h-3.5 text-slate-400" /> {job.stipend || job.salary}
            </span>
          )}
        </div>

        {/* Tailored Resume Snippet */}
        <div className="p-3 rounded-xl bg-slate-50 border border-slate-100 text-xs text-slate-600 my-3">
          <div className="font-semibold text-slate-700 mb-1 flex items-center gap-1">
            <FileText className="w-3.5 h-3.5 text-sky-600" /> Planned Tailored Resume:
          </div>
          <p className="line-clamp-2 text-slate-500 italic">"{resumeSummary}"</p>
        </div>

        {/* Skill Gaps (if any) */}
        {skillGaps.length > 0 && (
          <div className="my-3">
            <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3 text-amber-500" /> Top Skill Gaps to Prepare:
            </div>
            <div className="flex flex-wrap gap-1">
              {skillGaps.slice(0, 3).map((gap) => (
                <span
                  key={gap}
                  className="px-2 py-0.5 rounded-md bg-amber-50 text-amber-800 border border-amber-200/50 text-[11px] font-medium"
                >
                  {gap}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Card Footer Actions */}
      <div className="pt-4 border-t border-slate-100 flex items-center justify-between gap-2 mt-2">
        <div className="flex items-center gap-2">
          {/* Preview Resume Button */}
          <button
            type="button"
            onClick={() => onPreviewResume(job)}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-sky-50 hover:bg-sky-100 text-sky-700 text-xs font-semibold transition-colors cursor-pointer"
          >
            <FileText className="w-3.5 h-3.5" /> Preview Resume
          </button>

          {/* Prep Guide Link */}
          <Link
            to={`/prep-guide/${job.id || job.job_id}`}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition-colors"
          >
            <BookOpen className="w-3.5 h-3.5" /> Prep Guide
          </Link>
        </div>

        {/* Remove from Plan Button */}
        {canRemove && onRemove && (
          <button
            type="button"
            onClick={() => onRemove(job)}
            title="Remove and replace with next ranked opportunity"
            className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors cursor-pointer"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}
