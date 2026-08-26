import React from "react";
import { Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import ProfilePage from "./pages/ProfilePage";
import WeeklyPlanPage from "./pages/WeeklyPlanPage";
import ApplicationsPage from "./pages/ApplicationsPage";
import PrepGuidePage from "./pages/PrepGuidePage";
import ResumesPage from "./pages/ResumesPage";

export default function App() {
  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900">
      <Navbar />
      <main className="flex-1 pb-16">
        <Routes>
          <Route path="/" element={<ProfilePage />} />
          <Route path="/weekly-plan" element={<WeeklyPlanPage />} />
          <Route path="/applications" element={<ApplicationsPage />} />
          <Route path="/prep-guide/:id" element={<PrepGuidePage />} />
          <Route path="/resumes" element={<ResumesPage />} />
          {/* Fallback */}
          <Route path="*" element={<ProfilePage />} />
        </Routes>
      </main>
      <footer className="border-t border-slate-200 bg-white py-6 text-center text-xs text-slate-400">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <p>© 2026 HireFlow AI. All rights reserved. Automated job matching & application platform.</p>
        </div>
      </footer>
    </div>
  );
}
