import React from "react";
import { GraduationCap, Briefcase } from "lucide-react";

export default function ModeSelector({ mode, onChange, disabled = false }) {
  return (
    <div className="w-full">
      <label className="block text-sm font-semibold text-slate-700 mb-2">
        Target Opportunity Mode <span className="text-rose-500">*</span>
      </label>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Internship Option */}
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChange("internship")}
          aria-pressed={mode === "internship"}
          className={`flex items-start p-4 rounded-xl border-2 text-left transition-all duration-200 ${
            mode === "internship"
              ? "border-sky-500 bg-sky-50/70 text-sky-950 shadow-sm ring-2 ring-sky-500/20"
              : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50/50"
          } ${disabled ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}
        >
          <div
            className={`p-2.5 rounded-lg mr-3 ${
              mode === "internship"
                ? "bg-sky-500 text-white"
                : "bg-slate-100 text-slate-500"
            }`}
          >
            <GraduationCap className="w-5 h-5" />
          </div>
          <div>
            <div className="font-semibold text-base flex items-center gap-2">
              Internship Mode
              {mode === "internship" && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-sky-100 text-sky-800">
                  Active
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              Tailored for students & freshers. Focuses on coursework, projects, and learning agility.
            </p>
          </div>
        </button>

        {/* Full-time Job Option */}
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChange("job")}
          aria-pressed={mode === "job"}
          className={`flex items-start p-4 rounded-xl border-2 text-left transition-all duration-200 ${
            mode === "job"
              ? "border-indigo-500 bg-indigo-50/70 text-indigo-950 shadow-sm ring-2 ring-indigo-500/20"
              : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50/50"
          } ${disabled ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}
        >
          <div
            className={`p-2.5 rounded-lg mr-3 ${
              mode === "job"
                ? "bg-indigo-600 text-white"
                : "bg-slate-100 text-slate-500"
            }`}
          >
            <Briefcase className="w-5 h-5" />
          </div>
          <div>
            <div className="font-semibold text-base flex items-center gap-2">
              Full-time Job Mode
              {mode === "job" && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800">
                  Active
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              Tailored for full-time career roles. Emphasizes production experience, tech stack depth, and salary fit.
            </p>
          </div>
        </button>
      </div>
    </div>
  );
}
