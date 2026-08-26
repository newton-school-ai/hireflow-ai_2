import React from "react";
import { NavLink, Link } from "react-router-dom";
import { User, Calendar, FileText, Send, Sparkles } from "lucide-react";

export default function Navbar() {
  const navItems = [
    { to: "/", label: "Profile Setup", icon: User, end: true },
    { to: "/weekly-plan", label: "Weekly Plan", icon: Calendar },
    { to: "/applications", label: "Applications", icon: Send },
    { to: "/resumes", label: "Resumes", icon: FileText },
  ];

  return (
    <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-md border-b border-slate-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2.5 group">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-600 to-indigo-600 flex items-center justify-center text-white shadow-md shadow-sky-500/20 group-hover:scale-105 transition-transform">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <span className="font-bold text-lg tracking-tight text-slate-900 flex items-center gap-1.5">
                HireFlow <span className="text-xs px-1.5 py-0.5 rounded-md bg-sky-100 text-sky-700 font-semibold">AI</span>
              </span>
              <p className="text-[10px] text-slate-500 font-medium leading-none">Autonomous Placement Engine</p>
            </div>
          </Link>

          {/* Desktop Navigation */}
          <nav className="hidden md:flex items-center gap-1.5">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium transition-all ${
                      isActive
                        ? "bg-slate-900 text-white shadow-sm"
                        : "text-slate-600 hover:text-slate-900 hover:bg-slate-100/80"
                    }`
                  }
                >
                  <Icon className="w-4 h-4" />
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </nav>
        </div>
      </div>

      {/* Mobile Navigation bar */}
      <div className="md:hidden border-t border-slate-100 bg-white px-2 py-1.5 flex justify-around">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex flex-col items-center gap-0.5 px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                  isActive ? "text-sky-600 font-bold" : "text-slate-500 hover:text-slate-800"
                }`
              }
            >
              <Icon className="w-4 h-4" />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </div>
    </header>
  );
}
