"""GitHub repository scanner for generating assignment overviews."""
import re
from typing import Optional
from datetime import datetime

import httpx
import anthropic
import markdown

from app.config import settings


def parse_github_url(url: str) -> Optional[tuple[str, str]]:
    """Extract owner and repo from GitHub URL."""
    if not url:
        return None
    # Match patterns like: https://github.com/owner/repo or github.com/owner/repo
    pattern = r"(?:https?://)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$"
    match = re.match(pattern, url.strip())
    if match:
        return match.group(1), match.group(2)
    return None


async def fetch_repo_contents(owner: str, repo: str) -> dict:
    """Fetch repository README and file structure from GitHub API."""
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "CourseReviewPortal/1.0",
    }

    result = {
        "readme": None,
        "file_tree": [],
        "languages": {},
        "description": None,
        "error": None,
    }

    async with httpx.AsyncClient() as client:
        try:
            # Fetch repo info
            repo_resp = await client.get(base_url, headers=headers, timeout=10.0)
            if repo_resp.status_code == 200:
                repo_data = repo_resp.json()
                result["description"] = repo_data.get("description")

            # Fetch README
            readme_resp = await client.get(
                f"{base_url}/readme",
                headers={**headers, "Accept": "application/vnd.github.v3.raw"},
                timeout=10.0,
            )
            if readme_resp.status_code == 200:
                result["readme"] = readme_resp.text[:8000]  # Limit size

            # Fetch file tree (recursive, limited depth)
            tree_resp = await client.get(
                f"{base_url}/git/trees/main?recursive=1",
                headers=headers,
                timeout=10.0,
            )
            if tree_resp.status_code != 200:
                # Try 'master' branch
                tree_resp = await client.get(
                    f"{base_url}/git/trees/master?recursive=1",
                    headers=headers,
                    timeout=10.0,
                )

            if tree_resp.status_code == 200:
                tree_data = tree_resp.json()
                files = [
                    item["path"]
                    for item in tree_data.get("tree", [])
                    if item["type"] == "blob"
                ][:100]  # Limit to 100 files
                result["file_tree"] = files

            # Fetch languages
            lang_resp = await client.get(
                f"{base_url}/languages",
                headers=headers,
                timeout=10.0,
            )
            if lang_resp.status_code == 200:
                result["languages"] = lang_resp.json()

        except httpx.RequestError as e:
            result["error"] = f"Failed to fetch repository: {str(e)}"

    return result


async def generate_assignment_overview(
    module_name: str,
    repo_url: str,
    learning_objectives: Optional[list] = None,
) -> str:
    """Generate an AI overview of the assignment using Claude."""
    parsed = parse_github_url(repo_url)
    if not parsed:
        return "Unable to parse GitHub repository URL."

    owner, repo = parsed
    repo_contents = await fetch_repo_contents(owner, repo)

    if repo_contents.get("error"):
        return f"Error scanning repository: {repo_contents['error']}"

    # Build context for Claude
    context_parts = [f"# Repository: {owner}/{repo}"]

    if repo_contents["description"]:
        context_parts.append(f"\n## Description\n{repo_contents['description']}")

    if repo_contents["languages"]:
        langs = ", ".join(repo_contents["languages"].keys())
        context_parts.append(f"\n## Languages\n{langs}")

    if repo_contents["file_tree"]:
        tree_str = "\n".join(f"- {f}" for f in repo_contents["file_tree"][:50])
        context_parts.append(f"\n## File Structure\n{tree_str}")

    if repo_contents["readme"]:
        context_parts.append(f"\n## README\n{repo_contents['readme']}")

    context = "\n".join(context_parts)

    # Add learning objectives if available
    objectives_str = ""
    if learning_objectives:
        objectives_str = "\n\nLearning objectives for this module:\n" + "\n".join(
            f"- {obj}" for obj in learning_objectives
        )

    # Generate overview with Claude
    if not settings.ANTHROPIC_API_KEY:
        return "Anthropic API key not configured. Cannot generate AI overview."

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    prompt = f"""You are helping reviewers understand a course assignment for an Agentic AI Systems course.

Based on the following repository information, create a concise overview that helps a reviewer understand:

1. **What This Assignment Is About** - A brief summary of the assignment's purpose and what students will build
2. **Key Concepts & Technologies** - Main technologies, frameworks, or AI concepts being used
3. **What Students Are Expected To Do** - The main tasks or deliverables
4. **Things To Look For When Reviewing** - Specific areas reviewers should pay attention to (code quality, proper implementation of concepts, common mistakes to watch for)

{objectives_str}

Repository Information:
{context}

Please format your response in markdown with clear headings. Keep it concise but informative (aim for 300-400 words). Focus on what would be most helpful for someone reviewing student submissions."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as e:
        return f"Error generating overview: {str(e)}"


async def refresh_module_overview(db, module) -> str:
    """Refresh the assignment overview for a module.

    Note: This feature currently requires manual configuration of a template repo URL.
    GitHub Classroom URLs are invitation links, not direct repo URLs.
    """
    if not module.github_classroom_url:
        return "No GitHub Classroom URL configured for this module."

    # TODO: In the future, we could use the GitHub Classroom API to fetch
    # the template repository URL and scan it. For now, we generate a
    # placeholder overview based on module metadata.
    overview_md = await generate_assignment_overview(
        module_name=module.name,
        repo_url=None,  # Template repo scanning not yet implemented
        learning_objectives=module.learning_objectives,
    )

    # Convert markdown to HTML for display
    overview_html = markdown.markdown(
        overview_md,
        extensions=['tables', 'fenced_code', 'nl2br']
    )

    module.assignment_overview = overview_html
    module.overview_generated_at = datetime.utcnow()
    db.commit()

    return overview_html
