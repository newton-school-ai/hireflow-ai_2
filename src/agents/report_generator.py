"""
Weekly Report Generator for HireFlow AI.

Collects all applications from the current weekly cycle, enriches each
with job metadata and prep-guide information, computes cross-application
insights, renders a readable HTML report, and persists the result to
the weekly_reports table.

Usage (CLI):
    python -m src.agents.report_generator --user-id <uuid>
"""

from __future__ import annotations

import argparse
import json
import logging
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.models.application import Application
from src.models.job import Job
from src.models.prep_guide import PrepGuide
from src.models.report import WeeklyReport
from src.models.user import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Week helpers
# ---------------------------------------------------------------------------

WEEK_START_WEEKDAY = 0  # Monday


def _get_week_bounds(ref: date | None = None) -> tuple[date, date]:
    """Return (week_start, week_end) for the ISO week containing *ref*.

    The cycle runs Monday–Sunday. If *ref* is None, today is used.
    """
    ref = ref or datetime.now(tz=timezone.utc).date()
    # isoweekday(): Mon=1 … Sun=7
    days_since_monday = ref.isoweekday() - 1
    week_start = ref - timedelta(days=days_since_monday)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


# ---------------------------------------------------------------------------
# Sub-score category names (mirrors match_scorer.py)
# ---------------------------------------------------------------------------

SUB_SCORE_KEYS = ("skill", "role", "experience", "location", "compensation", "company")

# ---------------------------------------------------------------------------
# ReportGenerator
# ---------------------------------------------------------------------------


class ReportGenerator:
    """Generates weekly HTML reports and persists metadata to the DB.

    Attributes:
        output_root: Root directory where report files are saved.
    """

    def __init__(self, output_root: str | Path = "data/reports") -> None:
        self.output_root = Path(output_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_report(
        self,
        user_id: uuid.UUID | str,
        db: Session,
        week_ref: date | None = None,
    ) -> WeeklyReport:
        """Generate a weekly report for *user_id* and persist it.

        Args:
            user_id: Target user's UUID (or string form).
            db: Active SQLAlchemy session.
            week_ref: Optional reference date to fix the reporting week
                      (defaults to today).

        Returns:
            The persisted WeeklyReport ORM object.

        Raises:
            ValueError: If the user is not found.
        """
        uid = uuid.UUID(str(user_id))
        week_start, week_end = _get_week_bounds(week_ref)

        # --- 1. Validate user ---
        user: User | None = db.get(User, uid)
        if user is None:
            raise ValueError(f"User {uid!r} not found.")

        # --- 2. Load data (batch, no N+1) ---
        applications = self._load_applications(uid, week_start, week_end, db)
        jobs_by_id = self._load_jobs(applications, db)
        guides_by_job_id = self._load_prep_guides(uid, applications, db)

        # --- 3. Build enriched application records ---
        enriched = self._enrich_applications(applications, jobs_by_id, guides_by_job_id)

        # --- 4. Compute cross-application insights ---
        insights = self._compute_insights(enriched, jobs_by_id)

        # --- 5. Render HTML ---
        html_content = self._render_html(user, week_start, week_end, enriched, insights)

        # --- 6. Persist HTML + auxiliary JSON ---
        report_path = self._save_html(uid, week_start, html_content)
        self._save_json(uid, enriched, insights, week_start, week_end)

        # --- 7. Build DB record values ---
        applied_statuses = {"applied", "shortlisted", "confirmed", "resume_generated"}
        apps_sent = sum(1 for e in enriched if e["status"] in applied_statuses)

        top_matches_data = self._build_top_matches(enriched, insights)

        summary = self._build_summary(user, week_start, week_end, enriched, insights)

        # --- 8. Upsert WeeklyReport row ---
        report = self._upsert_report(
            uid=uid,
            week_start=week_start,
            week_end=week_end,
            applications_sent=apps_sent,
            top_matches=top_matches_data,
            summary=summary,
            report_path=str(report_path),
            db=db,
        )

        logger.info(
            "Weekly report generated for user=%s week=%s–%s  path=%s",
            uid,
            week_start,
            week_end,
            report_path,
        )
        return report

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_applications(
        self,
        uid: uuid.UUID,
        week_start: date,
        week_end: date,
        db: Session,
    ) -> list[Application]:
        """Load all applications for the user within the week window.

        The week bounds are applied against ``created_at`` because
        ``applied_at`` is only set once the user actually submits.
        Applications created at any point in the week are included.
        """
        week_start_dt = datetime(
            week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc
        )
        week_end_dt = datetime(
            week_end.year, week_end.month, week_end.day, 23, 59, 59, tzinfo=timezone.utc
        )

        stmt = (
            select(Application)
            .where(Application.user_id == uid)
            .where(Application.created_at >= week_start_dt)
            .where(Application.created_at <= week_end_dt)
            .order_by(Application.created_at.desc())
        )
        return list(db.scalars(stmt).all())

    def _load_jobs(
        self,
        applications: list[Application],
        db: Session,
    ) -> dict[uuid.UUID, Job]:
        """Batch-load jobs for the given applications."""
        if not applications:
            return {}
        job_ids = {app.job_id for app in applications}
        jobs = db.scalars(select(Job).where(Job.id.in_(job_ids))).all()
        return {j.id: j for j in jobs}

    def _load_prep_guides(
        self,
        uid: uuid.UUID,
        applications: list[Application],
        db: Session,
    ) -> dict[uuid.UUID, PrepGuide]:
        """Batch-load prep guides keyed by job_id."""
        if not applications:
            return {}
        job_ids = {app.job_id for app in applications}
        guides = db.scalars(
            select(PrepGuide)
            .where(PrepGuide.user_id == uid)
            .where(PrepGuide.job_id.in_(job_ids))
        ).all()
        return {g.job_id: g for g in guides if g.job_id is not None}

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    def _enrich_applications(
        self,
        applications: list[Application],
        jobs_by_id: dict[uuid.UUID, Job],
        guides_by_job_id: dict[uuid.UUID, PrepGuide],
    ) -> list[dict[str, Any]]:
        """Build a list of JSON-safe dicts with full per-application context."""
        enriched: list[dict[str, Any]] = []
        for app in applications:
            job: Job | None = jobs_by_id.get(app.job_id)
            guide: PrepGuide | None = guides_by_job_id.get(app.job_id)

            entry: dict[str, Any] = {
                "application_id": str(app.id),
                "job_id": str(app.job_id),
                # Job metadata
                "company": job.company_name if job else None,
                "role": job.role_title if job else None,
                "application_url": job.application_url if job else None,
                "listing_type": job.listing_type if job else None,
                "skills_required": (job.skills_required or []) if job else [],
                # Application fields
                "status": app.status,
                "match_score": app.match_score,
                "skill_matches": app.skill_matches or [],
                "skill_gaps": app.skill_gaps or [],
                "resume_path": app.resume_path,
                "resume_version": app.resume_version,
                "failure_reason": app.failure_reason,
                "applied_at": app.applied_at.isoformat() if app.applied_at else None,
                "created_at": app.created_at.isoformat() if app.created_at else None,
                # PrepGuide fields
                "prep_guide_id": str(guide.id) if guide else None,
                "prep_skill_gaps": (guide.skill_gaps or []) if guide else [],
                "prep_resources": (guide.resources or []) if guide else [],
                "prep_mock_questions": (guide.mock_questions or []) if guide else [],
                "prep_predicted_rounds": guide.predicted_rounds if guide else None,
                "prep_company_intel": (guide.company_intel or {}) if guide else {},
            }

            # needs_action gets an explicit manual URL
            if app.status == "needs_action":
                entry["manual_application_url"] = job.application_url if job else None

            enriched.append(entry)

        return enriched

    # ------------------------------------------------------------------
    # Insights
    # ------------------------------------------------------------------

    def _compute_insights(
        self,
        enriched: list[dict[str, Any]],
        jobs_by_id: dict[uuid.UUID, Job],
    ) -> dict[str, Any]:
        """Compute cross-application insights for the week."""
        if not enriched:
            return {
                "top_skills": [],
                "strongest_category": None,
                "weakest_category": None,
                "weekly_study_plan": [],
                "total_applications": 0,
                "applied_count": 0,
                "failed_count": 0,
                "needs_action_count": 0,
                "avg_match_score": None,
                "sub_score_averages": {},
            }

        # --- Top 5 skills (case-insensitive, sorted by freq then alpha) ---
        skill_counter: Counter[str] = Counter()
        skill_canonical: dict[str, str] = {}  # lower -> first-seen casing
        for e in enriched:
            for skill in e.get("skills_required", []):
                if not skill:
                    continue
                lower = str(skill).strip().lower()
                if lower not in skill_canonical:
                    skill_canonical[lower] = str(skill).strip()
                skill_counter[lower] += 1

        top5 = sorted(
            skill_counter.keys(),
            key=lambda s: (-skill_counter[s], s),
        )[:5]
        top_skills = [
            {"skill": skill_canonical[s], "count": skill_counter[s]} for s in top5
        ]

        # --- Sub-score averages (strongest / weakest) ---
        sub_score_totals: dict[str, float] = {k: 0.0 for k in SUB_SCORE_KEYS}
        sub_score_counts: dict[str, int] = {k: 0 for k in SUB_SCORE_KEYS}

        for e in enriched:
            match_score = e.get("match_score")
            if match_score is None:
                continue
            # We don't store per-sub-score in Application; if present use them.
            # Otherwise we approximate from match_score proportional.
            # (In practice, sub_scores are only available at score time, not persisted.)

        # Since sub_scores aren't persisted to Application, we derive
        # strongest/weakest from skill_matches vs skill_gaps counts.
        # skill ratio per application → proxy for skill sub-score.
        for e in enriched:
            required = e.get("skills_required") or []
            matched = e.get("skill_matches") or []
            if required:
                skill_ratio = len(matched) / len(required)
            else:
                skill_ratio = 1.0
            sub_score_totals["skill"] += skill_ratio
            sub_score_counts["skill"] += 1

            # match_score is the composite; back out other factors heuristically.
            ms = e.get("match_score")
            if ms is not None:
                # Use match_score as proxy for role/experience/location/compensation/company.
                for key in (
                    "role",
                    "experience",
                    "location",
                    "compensation",
                    "company",
                ):
                    sub_score_totals[key] += ms
                    sub_score_counts[key] += 1

        averages: dict[str, float] = {}
        for k in SUB_SCORE_KEYS:
            if sub_score_counts[k] > 0:
                averages[k] = round(sub_score_totals[k] / sub_score_counts[k], 4)

        strongest_category: str | None = None
        weakest_category: str | None = None
        if averages:
            strongest_category = max(averages, key=lambda k: averages[k])
            weakest_category = min(averages, key=lambda k: averages[k])

        # --- Average match score ---
        scores = [
            e["match_score"] for e in enriched if e.get("match_score") is not None
        ]
        avg_match = round(sum(scores) / len(scores), 4) if scores else None

        # --- Weekly study plan ---
        # Prioritise skills that are BOTH frequent in JDs AND gaps for the user.
        gap_skills: Counter[str] = Counter()
        gap_canonical: dict[str, str] = {}
        for e in enriched:
            all_gaps = list(e.get("skill_gaps") or []) + list(
                e.get("prep_skill_gaps") or []
            )
            for skill in all_gaps:
                if not skill:
                    continue
                lower = str(skill).strip().lower()
                if lower not in gap_canonical:
                    gap_canonical[lower] = str(skill).strip()
                gap_skills[lower] += 1

        # Combined score = frequency in JDs × occurrence as gap
        study_candidates: dict[str, float] = {}
        for lower, freq in skill_counter.items():
            gap_freq = gap_skills.get(lower, 0)
            if gap_freq > 0:  # only skills that are actual gaps
                study_candidates[lower] = freq * gap_freq

        study_plan_lower = sorted(
            study_candidates.keys(),
            key=lambda s: (-study_candidates[s], s),
        )[:3]
        study_plan = [
            {
                "skill": gap_canonical.get(s, skill_canonical.get(s, s)),
                "priority": i + 1,
            }
            for i, s in enumerate(study_plan_lower)
        ]

        # --- Status counts ---
        applied_statuses = {"applied", "shortlisted", "confirmed", "resume_generated"}
        applied_count = sum(1 for e in enriched if e["status"] in applied_statuses)
        failed_count = sum(1 for e in enriched if e["status"] == "failed")
        needs_action_count = sum(1 for e in enriched if e["status"] == "needs_action")

        return {
            "top_skills": top_skills,
            "strongest_category": strongest_category,
            "weakest_category": weakest_category,
            "weekly_study_plan": study_plan,
            "total_applications": len(enriched),
            "applied_count": applied_count,
            "failed_count": failed_count,
            "needs_action_count": needs_action_count,
            "avg_match_score": avg_match,
            "sub_score_averages": averages,
        }

    # ------------------------------------------------------------------
    # HTML rendering
    # ------------------------------------------------------------------

    def _render_html(
        self,
        user: User,
        week_start: date,
        week_end: date,
        enriched: list[dict[str, Any]],
        insights: dict[str, Any],
    ) -> str:
        """Render the full HTML report as a string."""
        week_label = (
            week_start.strftime("%B %d") + " – " + week_end.strftime("%B %d, %Y")
        )
        iso_week = week_start.isocalendar()[1]
        year = week_start.year

        # ---- Summary bar ----
        summary_rows = f"""
        <div class="stat"><span class="stat-val">{insights['total_applications']}</span><span class="stat-lbl">Total</span></div>
        <div class="stat"><span class="stat-val">{insights['applied_count']}</span><span class="stat-lbl">Applied</span></div>
        <div class="stat"><span class="stat-val">{insights['failed_count']}</span><span class="stat-lbl">Failed</span></div>
        <div class="stat"><span class="stat-val">{insights['needs_action_count']}</span><span class="stat-lbl">Needs Action</span></div>
        <div class="stat"><span class="stat-val">{f"{insights['avg_match_score']:.0%}" if insights['avg_match_score'] is not None else "–"}</span><span class="stat-lbl">Avg Match</span></div>
        """

        # ---- Insights panel ----
        top_skills_html = (
            "".join(
                f'<li><span class="skill-tag">{s["skill"]}</span> <span class="skill-cnt">×{s["count"]}</span></li>'
                for s in insights["top_skills"]
            )
            or "<li>No skill data available</li>"
        )

        study_html = (
            "".join(
                f'<li><span class="priority">#{p["priority"]}</span> {p["skill"]}</li>'
                for p in insights["weekly_study_plan"]
            )
            or "<li>No study recommendations</li>"
        )

        strongest = insights.get("strongest_category") or "—"
        weakest = insights.get("weakest_category") or "—"

        insights_html = f"""
        <div class="insights-grid">
          <div class="insight-card">
            <h3>🎯 Top 5 Skills This Week</h3>
            <ul class="skill-list">{top_skills_html}</ul>
          </div>
          <div class="insight-card">
            <h3>📈 Match Categories</h3>
            <p><strong>Strongest:</strong> <span class="badge badge-green">{strongest}</span></p>
            <p><strong>Weakest:</strong> <span class="badge badge-red">{weakest}</span></p>
          </div>
          <div class="insight-card">
            <h3>📚 Weekly Study Plan</h3>
            <ol class="study-list">{study_html}</ol>
          </div>
        </div>
        """

        # ---- Application cards ----
        STATUS_COLORS = {
            "applied": "#22c55e",
            "failed": "#ef4444",
            "needs_action": "#f97316",
            "resume_generated": "#3b82f6",
            "shortlisted": "#8b5cf6",
            "confirmed": "#10b981",
            "matched": "#6b7280",
            "planned": "#9ca3af",
            "withdrawn": "#d1d5db",
        }

        app_cards = []
        for e in enriched:
            color = STATUS_COLORS.get(e["status"], "#6b7280")
            score_pct = (
                f"{e['match_score']:.0%}" if e.get("match_score") is not None else "N/A"
            )
            skill_matches_html = (
                " ".join(
                    f'<span class="skill-tag matched">{s}</span>'
                    for s in (e.get("skill_matches") or [])[:6]
                )
                or "<em>None</em>"
            )
            skill_gaps_html = (
                " ".join(
                    f'<span class="skill-tag gap">{s}</span>'
                    for s in (e.get("skill_gaps") or [])[:6]
                )
                or "<em>None</em>"
            )
            resume_link = (
                f'<a href="{e["resume_path"]}" class="link">v{e["resume_version"]} →</a>'
                if e.get("resume_path")
                else "<em>Not generated</em>"
            )
            apply_url = e.get("application_url") or ""
            manual_url_html = ""
            if e["status"] in ("failed", "needs_action"):
                reason = e.get("failure_reason") or "Unknown reason"
                manual_url_html = f"""
                <div class="alert alert-warn">
                  <strong>⚠ {e['status'].replace('_',' ').title()}:</strong> {reason}
                </div>"""
                if e["status"] == "needs_action" and apply_url:
                    manual_url_html += f"""
                <div class="alert alert-action">
                  <strong>👉 Apply manually:</strong>
                  <a href="{apply_url}" class="link">{apply_url}</a>
                </div>"""

            prep_html = ""
            if e.get("prep_guide_id"):
                rounds = (
                    f" ({e['prep_predicted_rounds']} rounds)"
                    if e.get("prep_predicted_rounds")
                    else ""
                )
                prep_gaps = " ".join(
                    f'<span class="skill-tag gap">{s}</span>'
                    for s in (e.get("prep_skill_gaps") or [])[:4]
                )
                prep_html = f"""
                <div class="prep-section">
                  <span class="section-label">Prep Guide{rounds}:</span>
                  {prep_gaps or "<em>No extra gaps</em>"}
                </div>"""

            card = f"""
            <div class="app-card" style="border-left: 4px solid {color};">
              <div class="app-header">
                <div>
                  <span class="company">{e.get('company') or 'Unknown Company'}</span>
                  <span class="role">{e.get('role') or 'Unknown Role'}</span>
                </div>
                <div class="app-meta">
                  <span class="status-badge" style="background:{color};">{e['status'].replace('_',' ').upper()}</span>
                  <span class="score">{score_pct}</span>
                </div>
              </div>
              {manual_url_html}
              <div class="skills-row">
                <div><span class="section-label">Matches:</span> {skill_matches_html}</div>
                <div><span class="section-label">Gaps:</span> {skill_gaps_html}</div>
              </div>
              <div class="app-footer">
                <span><span class="section-label">Resume:</span> {resume_link}</span>
                {"<span><a href='" + apply_url + "' class='link'>Apply →</a></span>" if apply_url else ""}
              </div>
              {prep_html}
            </div>"""
            app_cards.append(card)

        apps_section = (
            "\n".join(app_cards)
            if app_cards
            else "<p class='empty'>No applications this week.</p>"
        )

        # ---- Full HTML ----
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>HireFlow Weekly Report — {week_label}</title>
  <style>
    :root {{
      --bg: #0f172a; --surface: #1e293b; --surface2: #334155;
      --accent: #6366f1; --text: #e2e8f0; --muted: #94a3b8;
      --green: #22c55e; --red: #ef4444; --orange: #f97316;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; padding: 2rem; line-height: 1.6; }}
    h1 {{ font-size: 1.8rem; font-weight: 700; color: var(--accent); margin-bottom: .25rem; }}
    h2 {{ font-size: 1.2rem; font-weight: 600; color: var(--muted); margin: 2rem 0 1rem; border-bottom: 1px solid var(--surface2); padding-bottom: .5rem; }}
    h3 {{ font-size: 1rem; font-weight: 600; margin-bottom: .75rem; }}
    .subtitle {{ color: var(--muted); font-size: .9rem; margin-bottom: 2rem; }}
    /* Stats */
    .stats-bar {{ display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 2rem; }}
    .stat {{ background: var(--surface); border-radius: 12px; padding: 1rem 1.5rem; text-align: center; }}
    .stat-val {{ display: block; font-size: 2rem; font-weight: 700; color: var(--accent); }}
    .stat-lbl {{ font-size: .75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }}
    /* Insights */
    .insights-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
    .insight-card {{ background: var(--surface); border-radius: 12px; padding: 1.25rem; }}
    .skill-list, .study-list {{ list-style: none; padding: 0; }}
    .skill-list li, .study-list li {{ padding: .25rem 0; display: flex; align-items: center; gap: .5rem; }}
    .skill-cnt {{ color: var(--muted); font-size: .8rem; }}
    .priority {{ color: var(--accent); font-weight: 700; width: 1.5rem; }}
    .badge {{ padding: .2rem .6rem; border-radius: 9999px; font-size: .75rem; font-weight: 600; }}
    .badge-green {{ background: #14532d; color: var(--green); }}
    .badge-red {{ background: #7f1d1d; color: var(--red); }}
    /* Cards */
    .app-card {{ background: var(--surface); border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; }}
    .app-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: .75rem; gap: 1rem; }}
    .company {{ font-weight: 700; font-size: 1.05rem; display: block; }}
    .role {{ color: var(--muted); font-size: .9rem; }}
    .app-meta {{ display: flex; align-items: center; gap: .75rem; flex-shrink: 0; }}
    .status-badge {{ padding: .2rem .6rem; border-radius: 9999px; font-size: .7rem; font-weight: 700; color: #fff; white-space: nowrap; }}
    .score {{ font-size: 1.1rem; font-weight: 700; color: var(--accent); }}
    .skills-row {{ display: flex; flex-direction: column; gap: .4rem; margin-bottom: .75rem; }}
    .skill-tag {{ display: inline-block; padding: .15rem .5rem; border-radius: 6px; font-size: .75rem; background: var(--surface2); margin: .1rem; }}
    .skill-tag.matched {{ background: #14532d; color: var(--green); }}
    .skill-tag.gap {{ background: #7f1d1d; color: var(--red); }}
    .section-label {{ font-size: .75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-right: .25rem; }}
    .app-footer {{ display: flex; gap: 1.5rem; font-size: .85rem; color: var(--muted); border-top: 1px solid var(--surface2); padding-top: .75rem; margin-top: .75rem; }}
    .prep-section {{ font-size: .85rem; color: var(--muted); margin-top: .5rem; }}
    .alert {{ padding: .6rem 1rem; border-radius: 8px; font-size: .85rem; margin: .5rem 0; }}
    .alert-warn {{ background: #431407; border-left: 3px solid var(--orange); }}
    .alert-action {{ background: #1a1a2e; border-left: 3px solid var(--accent); }}
    .link {{ color: var(--accent); text-decoration: none; }}
    .link:hover {{ text-decoration: underline; }}
    .empty {{ color: var(--muted); font-style: italic; text-align: center; padding: 2rem; }}
    footer {{ margin-top: 3rem; text-align: center; color: var(--muted); font-size: .8rem; }}
  </style>
</head>
<body>
  <h1>📋 HireFlow Weekly Report</h1>
  <p class="subtitle">
    Week {iso_week}, {year} &nbsp;·&nbsp; {week_label} &nbsp;·&nbsp;
    {user.name} ({user.email})
  </p>

  <div class="stats-bar">
    {summary_rows}
  </div>

  <h2>Cross-Application Insights</h2>
  {insights_html}

  <h2>Applications ({insights['total_applications']})</h2>
  {apps_section}

  <footer>Generated by HireFlow AI · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</footer>
</body>
</html>"""
        return html

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save_html(
        self,
        uid: uuid.UUID,
        week_start: date,
        html_content: str,
    ) -> Path:
        """Write HTML to ``data/reports/{user_id}/week_YYYY_WW.html``."""
        iso_week = week_start.isocalendar()[1]
        year = week_start.year
        filename = f"week_{year}_{iso_week:02d}.html"
        out_dir = self.output_root / str(uid)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / filename
        path.write_text(html_content, encoding="utf-8")
        return path

    def _save_json(
        self,
        uid: uuid.UUID,
        enriched: list[dict[str, Any]],
        insights: dict[str, Any],
        week_start: date,
        week_end: date,
    ) -> Path:
        """Write auxiliary ``latest.json`` for CLI verification."""
        payload = {
            "user_id": str(uid),
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "insights": insights,
            "applications": enriched,
        }
        out_dir = self.output_root / str(uid)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "latest.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def _build_top_matches(
        self,
        enriched: list[dict[str, Any]],
        insights: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build the top_matches JSON stored in WeeklyReport.top_matches.

        Stores the top 5 applications by match_score plus the full
        cross-application insights so the DB record is self-describing.
        """
        scored = sorted(
            [e for e in enriched if e.get("match_score") is not None],
            key=lambda x: -(x["match_score"] or 0),
        )[:5]

        top_apps = [
            {
                "application_id": e["application_id"],
                "company": e.get("company"),
                "role": e.get("role"),
                "status": e["status"],
                "match_score": e.get("match_score"),
            }
            for e in scored
        ]

        return [
            {
                "top_applications": top_apps,
                "insights": {
                    "top_skills": insights["top_skills"],
                    "strongest_category": insights.get("strongest_category"),
                    "weakest_category": insights.get("weakest_category"),
                    "weekly_study_plan": insights["weekly_study_plan"],
                    "avg_match_score": insights.get("avg_match_score"),
                    "sub_score_averages": insights.get("sub_score_averages", {}),
                    "total_applications": insights.get("total_applications", 0),
                    "applied_count": insights.get("applied_count", 0),
                    "failed_count": insights.get("failed_count", 0),
                    "needs_action_count": insights.get("needs_action_count", 0),
                },
            }
        ]

    def _build_summary(
        self,
        user: User,
        week_start: date,
        week_end: date,
        enriched: list[dict[str, Any]],
        insights: dict[str, Any],
    ) -> str:
        """Build a concise human-readable summary string for WeeklyReport.summary."""
        total = insights["total_applications"]
        applied = insights["applied_count"]
        failed = insights["failed_count"]
        na = insights["needs_action_count"]
        avg = (
            f"{insights['avg_match_score']:.0%}"
            if insights["avg_match_score"] is not None
            else "N/A"
        )
        study = ", ".join(p["skill"] for p in insights.get("weekly_study_plan", []))
        strongest = insights.get("strongest_category") or "N/A"
        weakest = insights.get("weakest_category") or "N/A"

        return (
            f"Week {week_start} to {week_end}: {total} applications, "
            f"{applied} applied, {failed} failed, {na} need manual action. "
            f"Avg match score: {avg}. "
            f"Strongest category: {strongest}. Weakest: {weakest}. "
            f"Study plan: {study or 'no recommendations'}."
        )

    def _upsert_report(
        self,
        uid: uuid.UUID,
        week_start: date,
        week_end: date,
        applications_sent: int,
        top_matches: list,
        summary: str,
        report_path: str,
        db: Session,
    ) -> WeeklyReport:
        """Insert or update the WeeklyReport row for this user+week."""
        existing = (
            db.query(WeeklyReport)
            .filter(
                WeeklyReport.user_id == uid,
                WeeklyReport.week_start == week_start,
            )
            .first()
        )
        if existing:
            existing.week_end = week_end
            existing.applications_sent = applications_sent
            existing.responses_received = 0  # Not tracked in current schema
            existing.top_matches = top_matches
            existing.summary = summary
            existing.report_path = report_path
            db.commit()
            db.refresh(existing)
            return existing

        report = WeeklyReport(
            user_id=uid,
            week_start=week_start,
            week_end=week_end,
            applications_sent=applications_sent,
            responses_received=0,  # Not tracked in current schema
            top_matches=top_matches,
            summary=summary,
            report_path=report_path,
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="HireFlow AI — Weekly Report Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--user-id",
        type=str,
        required=True,
        help="UUID string of the target user.",
    )
    parser.add_argument(
        "--output-root",
        type=str,
        default="data/reports",
        help="Root directory for generated reports (default: data/reports).",
    )
    parser.add_argument(
        "--week-ref",
        type=str,
        default=None,
        help="Optional ISO date (YYYY-MM-DD) to fix the reporting week.",
    )
    args = parser.parse_args()

    week_ref: date | None = None
    if args.week_ref:
        week_ref = date.fromisoformat(args.week_ref)

    db = SessionLocal()
    try:
        generator = ReportGenerator(output_root=args.output_root)
        report = generator.generate_report(
            user_id=args.user_id,
            db=db,
            week_ref=week_ref,
        )
        print(
            json.dumps(
                {
                    "report_id": str(report.id),
                    "user_id": str(report.user_id),
                    "week_start": report.week_start.isoformat(),
                    "week_end": report.week_end.isoformat(),
                    "applications_sent": report.applications_sent,
                    "report_path": report.report_path,
                    "summary": report.summary,
                },
                indent=2,
            )
        )
    except Exception:
        logger.exception("Report generation failed.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    _main()
