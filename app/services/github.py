"""
GitHub integration service for fetching grades from GitHub Classroom.

Uses a Personal Access Token (PAT) to access student repos and
fetch grading artifacts from GitHub Actions workflows.
"""

import json
import zipfile
import io
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

import httpx

from app.config import settings


@dataclass
class GradeSection:
    """A section of the grade report."""
    name: str
    score: float
    max_score: float
    details: list[str]


@dataclass
class GradeReport:
    """Complete grade report from GitHub Actions."""
    assignment: str
    timestamp: datetime
    total: float
    max_score: float
    percentage: float
    sections: list[GradeSection]
    errors: list[str]
    workflow_run_id: int
    workflow_url: str


class GitHubService:
    """Service for interacting with GitHub API."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or getattr(settings, 'GITHUB_PAT', None)
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    def _parse_repo_url(self, github_url: str) -> tuple[str, str]:
        """Extract owner and repo from GitHub URL."""
        # Handle various URL formats
        url = github_url.rstrip("/")

        if url.startswith("git@github.com:"):
            # git@github.com:owner/repo.git
            path = url.replace("git@github.com:", "").replace(".git", "")
        elif "github.com" in url:
            # https://github.com/owner/repo
            path = url.split("github.com/")[-1].replace(".git", "")
        else:
            raise ValueError(f"Invalid GitHub URL: {github_url}")

        parts = path.split("/")
        if len(parts) < 2:
            raise ValueError(f"Could not parse owner/repo from: {github_url}")

        return parts[0], parts[1]

    async def get_latest_workflow_run(
        self,
        github_url: str,
        workflow_name: str = "Autograding"
    ) -> Optional[dict]:
        """Get the latest workflow run for a repo."""
        owner, repo = self._parse_repo_url(github_url)

        async with httpx.AsyncClient() as client:
            # Get workflow runs
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/actions/runs",
                headers=self.headers,
                params={"per_page": 10}
            )

            if response.status_code == 404:
                return None

            response.raise_for_status()
            data = response.json()

            # Find the latest completed run for the grading workflow
            for run in data.get("workflow_runs", []):
                if workflow_name.lower() in run.get("name", "").lower():
                    if run.get("status") == "completed":
                        return run

            return None

    async def get_workflow_run_status(
        self,
        github_url: str,
        workflow_name: str = "Autograding"
    ) -> dict:
        """Get the status of the latest workflow run."""
        owner, repo = self._parse_repo_url(github_url)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/actions/runs",
                headers=self.headers,
                params={"per_page": 5}
            )

            if response.status_code == 404:
                return {"status": "not_found", "message": "Repository not found or no access"}

            if response.status_code == 403:
                return {"status": "no_access", "message": "No access to repository"}

            response.raise_for_status()
            data = response.json()

            for run in data.get("workflow_runs", []):
                if workflow_name.lower() in run.get("name", "").lower():
                    return {
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "run_id": run.get("id"),
                        "url": run.get("html_url"),
                        "created_at": run.get("created_at"),
                        "updated_at": run.get("updated_at"),
                    }

            return {"status": "no_workflow", "message": "No grading workflow found"}

    async def download_grade_artifact(
        self,
        github_url: str,
        artifact_name: str = "grade-report"
    ) -> Optional[dict]:
        """Download and parse the grade report artifact."""
        owner, repo = self._parse_repo_url(github_url)

        async with httpx.AsyncClient(follow_redirects=True) as client:
            # Get the latest workflow run
            run = await self.get_latest_workflow_run(github_url)
            if not run:
                return None

            run_id = run["id"]

            # Get artifacts for this run
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts",
                headers=self.headers
            )
            response.raise_for_status()

            artifacts = response.json().get("artifacts", [])

            # Find the grade report artifact
            artifact = None
            for a in artifacts:
                if artifact_name in a.get("name", ""):
                    artifact = a
                    break

            if not artifact:
                return None

            # Download the artifact (it's a zip file)
            download_url = artifact["archive_download_url"]
            response = await client.get(
                download_url,
                headers=self.headers
            )
            response.raise_for_status()

            # Extract the JSON from the zip
            zip_buffer = io.BytesIO(response.content)
            with zipfile.ZipFile(zip_buffer) as zf:
                # Find the JSON file in the zip
                for name in zf.namelist():
                    if name.endswith(".json"):
                        with zf.open(name) as f:
                            return json.load(f)

            return None

    async def fetch_grade_report(self, github_url: str) -> Optional[GradeReport]:
        """Fetch and parse the complete grade report."""
        run = await self.get_latest_workflow_run(github_url)
        if not run:
            return None

        artifact_data = await self.download_grade_artifact(github_url)
        if not artifact_data:
            return None

        # Parse into GradeReport
        sections = [
            GradeSection(
                name=s["name"],
                score=s["score"],
                max_score=s["max_score"],
                details=s.get("details", [])
            )
            for s in artifact_data.get("sections", [])
        ]

        return GradeReport(
            assignment=artifact_data.get("assignment", "unknown"),
            timestamp=datetime.fromisoformat(artifact_data.get("timestamp", datetime.utcnow().isoformat())),
            total=artifact_data.get("total", 0),
            max_score=artifact_data.get("max_score", 100),
            percentage=artifact_data.get("percentage", 0),
            sections=sections,
            errors=artifact_data.get("errors", []),
            workflow_run_id=run["id"],
            workflow_url=run["html_url"],
        )

    async def trigger_workflow(self, github_url: str, workflow_file: str = "grade.yml") -> bool:
        """Trigger a workflow dispatch event (re-run grading)."""
        owner, repo = self._parse_repo_url(github_url)

        async with httpx.AsyncClient() as client:
            # Get default branch
            response = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}",
                headers=self.headers
            )
            response.raise_for_status()
            default_branch = response.json().get("default_branch", "main")

            # Trigger workflow
            response = await client.post(
                f"{self.base_url}/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches",
                headers=self.headers,
                json={"ref": default_branch}
            )

            return response.status_code == 204


# Singleton instance
github_service = GitHubService()
