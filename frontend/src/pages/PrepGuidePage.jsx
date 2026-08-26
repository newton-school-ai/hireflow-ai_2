import React from "react";
import { useParams, Link } from "react-router-dom";
import { BookOpen, ArrowLeft, CheckCircle } from "lucide-react";

export default function PrepGuidePage() {
  const { id } = useParams();

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-12">
      <Link to="/" className="inline-flex items-center gap-2 text-xs font-semibold text-slate-500 hover:text-slate-900 mb-6">
        <ArrowLeft className="w-4 h-4" /> Back to Dashboard
      </Link>

      <div className="bg-white p-8 rounded-2xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-12 h-12 bg-amber-100 text-amber-600 rounded-xl flex items-center justify-center">
            <BookOpen className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">AI Interview Prep Guide</h1>
            <p className="text-xs font-mono text-slate-500">Opportunity ID: {id || "sample-guide"}</p>
          </div>
        </div>

        <div className="p-6 bg-slate-50 rounded-xl border border-slate-100">
          <div className="flex items-center gap-2 text-emerald-700 font-semibold text-sm mb-2">
            <CheckCircle className="w-4 h-4" /> Round Structure & Mock Questions Ready
          </div>
          <p className="text-sm text-slate-600">
            Interview round predictor, categorized skill topics, and AI-generated practice questions will be rendered here for Issue 25.
          </p>
        </div>
      </div>
    </div>
  );
}
