"""
LaTeX PDF Generator and Resume Storage Pipeline for HireFlow AI.

Converts structured resume content into a professional, ATS-friendly PDF resume,
maintains automatic version history on disk, and updates the corresponding
application database record.
"""

import logging
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.config.settings import settings as default_settings
from src.models.application import Application
from src.models.job import Job
from src.models.user import User

logger = logging.getLogger(__name__)


# =============================================================================
# Custom Exception Hierarchy
# =============================================================================


class PDFGeneratorError(Exception):
    """Base exception for PDF generator pipeline errors."""


class UserNotFoundError(PDFGeneratorError, ValueError):
    """Raised when a specified user ID is not found in the database."""


class JobNotFoundError(PDFGeneratorError, ValueError):
    """Raised when a specified job ID is not found in the database."""


class InvalidResumeContentError(PDFGeneratorError, ValueError):
    """Raised when resume content dictionary is missing or structurally invalid."""


class LaTeXCompilationError(PDFGeneratorError, RuntimeError):
    """Raised when LaTeX compilation fails or the LaTeX compiler is missing."""


class LaTeXTemplateNotFoundError(PDFGeneratorError, FileNotFoundError):
    """Raised when the requested LaTeX template file is not found."""


class StorageError(PDFGeneratorError, OSError):
    """Raised when writing the generated PDF to disk fails."""


# =============================================================================
# LaTeX Escaping Utilities
# =============================================================================

_LATEX_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_REGEX = re.compile("|".join(re.escape(k) for k in _LATEX_MAP))


def _escape_latex(text: Any) -> str:
    """Escapes special LaTeX characters to prevent TeX syntax errors.

    Args:
        text: Any text content to be safely rendered in LaTeX.

    Returns:
        String with all special TeX characters properly escaped.
    """
    if text is None:
        return ""
    val = str(text)
    return _LATEX_REGEX.sub(lambda m: _LATEX_MAP[m.group(0)], val)


def _safe_uuid(val: Any) -> uuid.UUID:
    """Converts string or UUID instance into a valid uuid.UUID object.

    Args:
        val: UUID string or object.

    Returns:
        uuid.UUID object.

    Raises:
        ValueError: If val cannot be converted into a valid UUID.
    """
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError, AttributeError) as e:
        raise ValueError(f"Invalid UUID: {val!r}") from e


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class PDFGenerationResult:
    """Result of a successful PDF resume generation run.

    Attributes:
        user_id: UUID of the candidate.
        job_id: UUID of the target job listing.
        resume_path: String path where the PDF was saved.
        version: Version number of the generated PDF.
        file_path: Path object pointing to the output PDF.
    """

    user_id: uuid.UUID
    job_id: uuid.UUID
    resume_path: str
    version: int
    file_path: Path

    def __iter__(self):
        """Allows tuple unpacking: path, version = result."""
        return iter((self.resume_path, self.version))


# =============================================================================
# PDF Generator Core Pipeline
# =============================================================================


class PDFGenerator:
    """Generates ATS-friendly PDF resumes from structured data using LaTeX.

    Handles data validation, TeX character escaping, template rendering,
    pdflatex compilation, automatic filesystem versioning, and application
    database record synchronization.
    """

    def __init__(
        self,
        storage_path: str | Path | None = None,
        template_path: str | Path | None = None,
        compiler: str = "pdflatex",
        settings_obj: Any | None = None,
    ) -> None:
        """Initialize PDFGenerator with optional custom storage, template, or compiler.

        Args:
            storage_path: Root directory for saving resume PDFs. Defaults to settings.local_storage_path / resumes.
            template_path: File path to the base .tex Jinja template.
            compiler: Name of the system LaTeX compiler binary (default: 'pdflatex').
            settings_obj: Settings instance for configuration. Defaults to app settings.
        """
        self.settings = settings_obj or default_settings

        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            base_storage = Path(getattr(self.settings, "local_storage_path", "./data"))
            self.storage_path = base_storage / "resumes"

        if template_path:
            self.template_path = Path(template_path)
        else:
            self.template_path = (
                Path(__file__).resolve().parent.parent
                / "templates"
                / "resume_latex"
                / "base_template.tex"
            )

        self.compiler = compiler

    def generate(
        self,
        user_id: uuid.UUID | str,
        job_id: uuid.UUID | str,
        resume_content: dict[str, Any],
        db: Session | None = None,
    ) -> PDFGenerationResult:
        """Generate a tailored resume PDF for a user and job application.

        Args:
            user_id: UUID of the candidate user.
            job_id: UUID of the job position.
            resume_content: Structured resume dictionary (skills, experience, projects, etc.).
            db: Optional SQLAlchemy Session. If omitted, a session is managed automatically.

        Returns:
            PDFGenerationResult containing output path, version, and IDs.

        Raises:
            UserNotFoundError: If user_id does not exist in the database.
            JobNotFoundError: If job_id does not exist in the database.
            InvalidResumeContentError: If resume_content is empty or malformed.
            LaTeXCompilationError: If LaTeX compilation fails or compiler is missing.
            LaTeXTemplateNotFoundError: If base LaTeX template is missing.
            StorageError: If saving PDF file to disk fails.
        """
        u_id = _safe_uuid(user_id)
        j_id = _safe_uuid(job_id)

        self._validate_resume(resume_content)

        # Database verification and record preparation
        db_provided = db is not None
        session = db if db_provided else SessionLocal()

        try:
            self._verify_entities_exist(u_id, j_id, session)

            version = self._get_next_version(u_id, j_id)
            context = self._prepare_context(resume_content)
            latex_code = self._render_latex(context)

            temp_dir = Path(tempfile.mkdtemp(prefix="hireflow_pdf_"))
            try:
                pdf_bytes = self._compile_pdf(latex_code, temp_dir)
            finally:
                self._cleanup_temp_files(temp_dir)

            output_path = self._save_pdf(pdf_bytes, u_id, j_id, version)

            self._update_application_record(
                user_id=u_id,
                job_id=j_id,
                resume_path=str(output_path),
                version=version,
                db=session,
            )

            if not db_provided:
                session.commit()

            logger.info(
                f"Successfully generated resume v{version} for user {u_id} and job {j_id} at {output_path}"
            )

            return PDFGenerationResult(
                user_id=u_id,
                job_id=j_id,
                resume_path=str(output_path),
                version=version,
                file_path=output_path,
            )

        except Exception:
            if not db_provided and session:
                session.rollback()
            raise
        finally:
            if not db_provided and session:
                session.close()

    def _validate_resume(self, resume_content: dict[str, Any]) -> None:
        """Validates that resume content dictionary is non-empty and well-structured.

        Args:
            resume_content: Dictionary containing resume details.

        Raises:
            InvalidResumeContentError: If resume_content is not a non-empty dictionary.
        """
        if not isinstance(resume_content, dict) or not resume_content:
            raise InvalidResumeContentError(
                "Resume content must be a non-empty dictionary."
            )

        valid_keys = {
            "name",
            "contact",
            "summary",
            "skills",
            "experience",
            "projects",
            "education",
        }
        has_content = any(k in resume_content and resume_content[k] for k in valid_keys)
        if not has_content:
            raise InvalidResumeContentError(
                "Resume content must contain at least one standard section "
                "(name, contact, summary, skills, experience, projects, education)."
            )

    def _verify_entities_exist(
        self, user_id: uuid.UUID, job_id: uuid.UUID, db: Session
    ) -> None:
        """Verifies User and Job records exist in the database.

        Args:
            user_id: UUID of user.
            job_id: UUID of job.
            db: Active database session.

        Raises:
            UserNotFoundError: If candidate user does not exist.
            JobNotFoundError: If job record does not exist.
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")

        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise JobNotFoundError(f"Job with ID '{job_id}' not found.")

    def _prepare_context(self, resume_content: dict[str, Any]) -> dict[str, Any]:
        """Prepares and escapes resume dictionary values for LaTeX rendering.

        Args:
            resume_content: Raw resume dictionary.

        Returns:
            Sanitized, LaTeX-safe context dictionary.
        """
        context: dict[str, Any] = {}

        # 1. Candidate Name
        context["name"] = _escape_latex(resume_content.get("name", "Candidate"))

        # 2. Contact Line
        contact_raw = resume_content.get("contact", {})
        if isinstance(contact_raw, dict):
            parts = []
            for key in ["email", "phone", "location", "linkedin", "github", "website"]:
                val = contact_raw.get(key)
                if val:
                    parts.append(_escape_latex(val))
            context["contact_str"] = " \\textbullet{} ".join(parts)
        elif isinstance(contact_raw, str):
            context["contact_str"] = _escape_latex(contact_raw)
        else:
            context["contact_str"] = ""

        # 3. Professional Summary
        context["summary"] = _escape_latex(resume_content.get("summary", ""))

        # 4. Skills
        skills_raw = resume_content.get("skills")
        context["skills"] = bool(skills_raw)
        context["skills_categories"] = []
        context["skills_list"] = ""
        context["skills_str"] = ""

        if isinstance(skills_raw, dict):
            categories = []
            for cat_name, items in skills_raw.items():
                if isinstance(items, list):
                    item_str = ", ".join(_escape_latex(i) for i in items if i)
                else:
                    item_str = _escape_latex(items)
                if item_str:
                    categories.append(
                        {
                            "name": _escape_latex(cat_name),
                            "skills_str": item_str,
                        }
                    )
            context["skills_categories"] = categories
        elif isinstance(skills_raw, list):
            context["skills_list"] = ", ".join(
                _escape_latex(s) for s in skills_raw if s
            )
        elif isinstance(skills_raw, str):
            context["skills_str"] = _escape_latex(skills_raw)

        # 5. Experience
        exp_list = []
        for exp in resume_content.get("experience", []) or []:
            if not isinstance(exp, dict):
                continue
            highlights = [
                _escape_latex(h)
                for h in (exp.get("highlights") or [])
                if _escape_latex(h)
            ]
            exp_list.append(
                {
                    "title": _escape_latex(exp.get("title", "")),
                    "company": _escape_latex(exp.get("company", "")),
                    "location": _escape_latex(exp.get("location", "")),
                    "dates": _escape_latex(exp.get("dates", "")),
                    "description": _escape_latex(exp.get("description", "")),
                    "highlights": highlights,
                }
            )
        context["experience"] = exp_list

        # 6. Projects
        proj_list = []
        for proj in resume_content.get("projects", []) or []:
            if not isinstance(proj, dict):
                continue
            techs = proj.get("technologies") or []
            if isinstance(techs, list):
                tech_str = ", ".join(_escape_latex(t) for t in techs if t)
            else:
                tech_str = _escape_latex(techs)

            highlights = [
                _escape_latex(h)
                for h in (proj.get("highlights") or [])
                if _escape_latex(h)
            ]

            proj_list.append(
                {
                    "name": _escape_latex(proj.get("name", "")),
                    "technologies_str": tech_str,
                    "link": _escape_latex(proj.get("link", "")),
                    "description": _escape_latex(proj.get("description", "")),
                    "highlights": highlights,
                }
            )
        context["projects"] = proj_list

        # 7. Education
        edu_list = []
        for edu in resume_content.get("education", []) or []:
            if not isinstance(edu, dict):
                continue
            edu_list.append(
                {
                    "degree": _escape_latex(edu.get("degree", "")),
                    "institution": _escape_latex(edu.get("institution", "")),
                    "location": _escape_latex(edu.get("location", "")),
                    "dates": _escape_latex(edu.get("dates", "")),
                    "details": _escape_latex(edu.get("details", "")),
                }
            )
        context["education"] = edu_list

        return context

    def _render_latex(self, context: dict[str, Any]) -> str:
        """Renders LaTeX string using Jinja2 and the base template.

        Args:
            context: LaTeX-safe dictionary context.

        Returns:
            Rendered LaTeX string.

        Raises:
            LaTeXTemplateNotFoundError: If the template file is missing.
        """
        if not self.template_path.exists():
            raise LaTeXTemplateNotFoundError(
                f"Base LaTeX template file not found at '{self.template_path}'."
            )

        template_dir = self.template_path.parent
        template_filename = self.template_path.name

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            block_start_string=r"\BLOCK{",
            block_end_string="}",
            variable_start_string=r"\VAR{",
            variable_end_string="}",
            comment_start_string=r"\#{",
            comment_end_string="}",
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

        template = env.get_template(template_filename)
        return template.render(**context)

    def _compile_pdf(self, latex_content: str, temp_dir: Path) -> bytes:
        """Compiles LaTeX string into PDF binary content.

        Args:
            latex_content: Full LaTeX source code.
            temp_dir: Temporary directory for compilation artifacts.

        Returns:
            Raw PDF bytes.

        Raises:
            LaTeXCompilationError: If pdflatex binary is missing or compilation fails.
        """
        tex_file = temp_dir / "resume.tex"
        tex_file.write_text(latex_content, encoding="utf-8")

        if not shutil.which(self.compiler):
            raise LaTeXCompilationError(
                f"LaTeX compiler '{self.compiler}' is not installed or available on PATH."
            )

        cmd = [
            self.compiler,
            "-interaction=nonstopmode",
            f"-output-directory={temp_dir}",
            str(tex_file),
        ]

        try:
            res = subprocess.run(
                cmd,
                cwd=str(temp_dir),
                capture_output=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise LaTeXCompilationError(
                f"LaTeX compilation timed out after 30 seconds: {e}"
            ) from e
        except Exception as e:
            raise LaTeXCompilationError(
                f"Failed to execute LaTeX compiler '{self.compiler}': {e}"
            ) from e

        pdf_file = temp_dir / "resume.pdf"
        if res.returncode != 0 or not pdf_file.exists():
            log_file = temp_dir / "resume.log"
            log_tail = ""
            if log_file.exists():
                log_tail = log_file.read_text(encoding="utf-8", errors="ignore")[-1000:]
            err_msg = res.stderr.decode("utf-8", errors="ignore") or log_tail
            raise LaTeXCompilationError(
                f"LaTeX compilation failed with exit code {res.returncode}. Log snippet:\n{err_msg}"
            )

        return pdf_file.read_bytes()

    def _get_next_version(self, user_id: uuid.UUID, job_id: uuid.UUID) -> int:
        """Determines next incremental version number for user and job.

        Args:
            user_id: User UUID.
            job_id: Job UUID.

        Returns:
            Next version integer (starts at 1).
        """
        user_dir = self.storage_path / str(user_id)
        if not user_dir.exists():
            return 1

        pattern = re.compile(rf"^{re.escape(str(job_id))}_resume_v(\d+)\.pdf$")
        versions: list[int] = []

        for item in user_dir.iterdir():
            if item.is_file():
                match = pattern.match(item.name)
                if match:
                    versions.append(int(match.group(1)))

        return max(versions) + 1 if versions else 1

    def _save_pdf(
        self,
        pdf_bytes: bytes,
        user_id: uuid.UUID,
        job_id: uuid.UUID,
        version: int,
    ) -> Path:
        """Saves generated PDF bytes to the deterministic versioned path.

        Args:
            pdf_bytes: Raw binary PDF content.
            user_id: User UUID.
            job_id: Job UUID.
            version: Version integer.

        Returns:
            Absolute Path object pointing to saved PDF file.

        Raises:
            StorageError: If disk writing fails.
        """
        user_dir = self.storage_path / str(user_id)
        try:
            user_dir.mkdir(parents=True, exist_ok=True)
            output_file = user_dir / f"{job_id}_resume_v{version}.pdf"

            # Avoid race condition overwrites
            current_ver = version
            while output_file.exists():
                current_ver += 1
                output_file = user_dir / f"{job_id}_resume_v{current_ver}.pdf"

            output_file.write_bytes(pdf_bytes)
            return output_file.resolve()
        except Exception as e:
            raise StorageError(
                f"Failed to save resume PDF for user {user_id} and job {job_id}: {e}"
            ) from e

    def _update_application_record(
        self,
        user_id: uuid.UUID,
        job_id: uuid.UUID,
        resume_path: str,
        version: int,
        db: Session,
    ) -> Application:
        """Updates or creates the database Application record with resume path and version.

        Args:
            user_id: Candidate user UUID.
            job_id: Target job UUID.
            resume_path: String path to saved resume PDF.
            version: Resume version number.
            db: Database session.

        Returns:
            Updated Application instance.
        """
        app = (
            db.query(Application)
            .filter(Application.user_id == user_id, Application.job_id == job_id)
            .first()
        )

        if not app:
            app = Application(
                user_id=user_id,
                job_id=job_id,
                resume_path=resume_path,
                resume_version=version,
                status="resume_generated",
            )
            db.add(app)
        else:
            app.resume_path = resume_path
            app.resume_version = version
            app.status = "resume_generated"

        db.flush()
        return app

    def _cleanup_temp_files(self, temp_dir: Path | str | None) -> None:
        """Safely removes temporary compilation directory.

        Args:
            temp_dir: Path or string to temporary folder.
        """
        if temp_dir and Path(temp_dir).exists():
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except (OSError, RuntimeError) as e:
                logger.warning(
                    f"Failed to clean up temporary directory {temp_dir}: {e}"
                )
