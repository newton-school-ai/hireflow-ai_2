import React from "react";
import { Calendar, ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

export default function WeeklyPlanPage() {
  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-12 text-center">
      <div className="w-16 h-16 bg-sky-100 text-sky-600 rounded-2xl flex items-center justify-center mx-auto mb-4">
        <Calendar className="w-8 h-8" />
      </div>
      <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Weekly Plan & Opportunity Batch</h1>
      <p className="text-slate-600 mt-2 max-w-md mx-auto">
        Your tailored weekly job batch selected by the FAISS embedding & multi-factor match scorer.
      </p>
      <div className="mt-8 p-8 border border-dashed border-slate-300 rounded-2xl bg-white/50">
        <p className="text-sm font-medium text-slate-500">
          Module ready for Issue 24 integration. Register your profile to generate your first weekly batch.
        </p>
        <Link
          to="/"
          className="inline-flex items-center gap-2 mt-4 px-5 py-2.5 bg-slate-900 text-white rounded-xl text-sm font-semibold hover:bg-slate-800 transition-colors"
        >
          Go to Profile Setup <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    </div>
  );
}
