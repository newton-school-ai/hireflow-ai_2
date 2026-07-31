"""Pipeline for generating LaTeX-based PDF resumes."""

import logging
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import jinja2

from src.config.database import SessionLocal
from src.config.settings import settings
from src.models.application import Application

logger = logging.getLogger(__name__)

# Base directory for latex templates
TEMPLATE_DIR = Path("src/templates/resume_latex")


class PDFGenerator:
    """Handles the generation of ATS-friendly PDF resumes from LaTeX templates.

    Responsibilities:
    - Rendering data into LaTeX using Jinja2
    - Compiling PDFs using XeLaTeX
    - Version management on the filesystem
    - Updating database Application records safely
    """

    def __init__(self) -> None:
        """Initialize the Jinja2 environment with LaTeX-safe delimiters."""
        self.output_dir = Path(settings.resume_output_dir)

        # We configure Jinja2 to use tags that do not conflict with LaTeX's {}
        self.jinja_env = jinja2.Environment(
            block_start_string="\\BLOCK{",
            block_end_string="}",
            variable_start_string="\\VAR{",
            variable_end_string="}",
            comment_start_string="\\#{",
            comment_end_string="}",
            line_statement_prefix="%%",
            line_comment_prefix="%#",
            trim_blocks=True,
            autoescape=False,
            loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        )

    def _get_user_dir(self, user_id: uuid.UUID | str) -> Path:
        """Create and return the user's specific output directory."""
        user_dir = self.output_dir / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _get_next_version(self, user_dir: Path, job_id: uuid.UUID | str) -> int:
        """Determine the next available resume version number for this job."""
        prefix = f"{job_id}_resume_v"
        existing_versions = []

        # Scan for existing files matching the pattern
        if user_dir.exists():
            for filepath in user_dir.glob(f"{prefix}*.pdf"):
                match = re.search(r"_v(\d+)\.pdf$", filepath.name)
                if match:
                    existing_versions.append(int(match.group(1)))

        if not existing_versions:
            return 1

        return max(existing_versions) + 1

    def _escape_latex(self, text: str) -> str:
        """Escape LaTeX special characters to prevent compilation errors."""
        if not isinstance(text, str):
            return text

        # Basic escaping for standard LaTeX special chars
        chars = {
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
            "\\": r"\textbackslash{}",
        }
        # Escape backslash first to avoid double-escaping
        res = text.replace("\\", chars["\\"])
        for k, v in chars.items():
            if k != "\\":
                res = res.replace(k, v)
        return res

    def _process_data_for_latex(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively escape strings in the resume data."""
        if isinstance(data, dict):
            return {k: self._process_data_for_latex(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._process_data_for_latex(item) for item in data]
        elif isinstance(data, str):
            return self._escape_latex(data)
        return data

    def _render_tex(self, resume_content: dict[str, Any], temp_tex_path: Path) -> None:
        """Render the resume data into the LaTeX template and save to disk."""
        template = self.jinja_env.get_template("base_template.tex")
        safe_data = self._process_data_for_latex(resume_content)

        rendered_content = template.render(**safe_data)

        with open(temp_tex_path, "w", encoding="utf-8") as f:
            f.write(rendered_content)

    def _compile_latex(self, tex_path: Path, output_dir: Path) -> None:
        """Run XeLaTeX to compile the given .tex file into a PDF."""
        if not shutil.which("xelatex"):
            raise RuntimeError(
                "XeLaTeX is not installed. Please install MacTeX or ensure xelatex is available in PATH."
            )
        # Run non-interactive xelatex compilation
        command = [
            "xelatex",
            "-interaction=nonstopmode",
            f"-output-directory={output_dir}",
            str(tex_path),
        ]

        result = subprocess.run(command, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            logger.error(f"XeLaTeX compilation failed for {tex_path.name}")
            raise RuntimeError(
                f"XeLaTeX compilation failed with exit code {result.returncode}.\n"
                f"Stdout: {result.stdout}\n"
                f"Stderr: {result.stderr}"
            )

    def generate(
        self, user_id: str, job_id: str, resume_content: dict[str, Any]
    ) -> str:
        """Generate a PDF resume, save it, and update the database record.

        Args:
            user_id: The ID of the applying user.
            job_id: The ID of the target job.
            resume_content: Dictionary containing resume details (name, summary, etc.)

        Returns:
            The file path of the generated PDF.

        Raises:
            RuntimeError: If LaTeX compilation or database update fails.
        """
        logger.info(f"Starting PDF generation for User {user_id}, Job {job_id}")

        db = SessionLocal()
        try:
            # 1. Fetch application (optional for pure local testing)
            app = None
            try:
                # Ensure they are valid UUIDs before querying Postgres to prevent DataError
                uuid.UUID(str(user_id))
                uuid.UUID(str(job_id))
                app = (
                    db.query(Application)
                    .filter(
                        Application.user_id == user_id, Application.job_id == job_id
                    )
                    .first()
                )
            except ValueError:
                pass  # Not valid UUIDs (e.g., 'test_user'), just skip DB lookup

            # 2. Determine paths and version
            user_dir = self._get_user_dir(user_id)
            version = self._get_next_version(user_dir, job_id)
            logger.info(
                f"Selected resume version: v{version} for user {user_id}, job {job_id}"
            )

            base_filename = f"{job_id}_resume_v{version}"
            pdf_path = user_dir / f"{base_filename}.pdf"

            # 3. Render and Compile Atomically
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_dir_path = Path(temp_dir)
                temp_tex_path = temp_dir_path / f"{base_filename}.tex"
                temp_pdf_path = temp_dir_path / f"{base_filename}.pdf"

                self._render_tex(resume_content, temp_tex_path)
                self._compile_latex(temp_tex_path, temp_dir_path)

                if not temp_pdf_path.exists():
                    raise RuntimeError("PDF file was not created by XeLaTeX.")

                # Move atomically to final destination
                shutil.move(str(temp_pdf_path), str(pdf_path))

            logger.info(f"PDF generated successfully at {pdf_path}")

            # 4. Update Database
            if app:
                app.resume_path = str(pdf_path)
                app.resume_version = version
                # Optionally update status
                if app.status == "matched":
                    app.status = "resume_generated"

                db.commit()
                logger.info(f"Database updated for Application {app.id}")
            else:
                logger.warning(
                    f"No Application found for User {user_id}, Job {job_id}. Skipping DB update for local test."
                )

            return str(pdf_path)

        except Exception as e:
            db.rollback()
            logger.error(
                f"Failed to generate PDF for User {user_id}, Job {job_id}: {e}"
            )
            raise
        finally:
            db.close()
