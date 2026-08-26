import React from "react";
import { FileText, Download } from "lucide-react";

export default function ResumesPage() {
  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-12 text-center">
      <div className="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-2xl flex items-center justify-center mx-auto mb-4">
        <FileText className="w-8 h-8" />
      </div>
      <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Tailored Resume Library</h1>
      <p className="text-slate-600 mt-2 max-w-md mx-auto">
        Inspect and download ATS-optimized PDF resumes tailored by the LLM tailoring engine.
      </p>
      <div className="mt-8 p-8 border border-dashed border-slate-300 rounded-2xl bg-white/50">
        <div className="flex items-center justify-center gap-2 text-xs font-semibold text-emerald-600 mb-2 uppercase tracking-wider">
          <Download className="w-4 h-4" /> PDF Artifacts
        </div>
        <p className="text-sm font-medium text-slate-500">
          Module ready for Issue 25 integration. All tailored resumes will be accessible for preview and download.
        </p>
      </div>
    </div>
  );
}
