# Reading the handbook as a website

The website uses the repository's Markdown as its source. Edit the README introduction, the build roadmap or a chapter under `handbook/`; then rebuild. The existing chapter renderer supplies the resolved statistics and code citations. The generated website files are ignored by Git.

The reading view includes chapter navigation, search, light and dark themes, diagrams and links to the source. The build sequence of lessons is the main reading path; the roadmap page is its map, and the offline lab is lesson 1's starting point.

## Preview locally

From the repository root, in an activated Python environment:

```bash
python -m pip install -r requirements-docs.txt
python scripts/build_site.py
python -m mkdocs build --strict
python scripts/check_site.py
python -m mkdocs serve --dev-addr 127.0.0.1:8000
```

Open the local address printed by the server. After changing a chapter, run the preparation command again. `mkdocs serve` watches the generated Markdown, not the original chapters.

For a private repository preview, set `HANDBOOK_REPOSITORY` to its `owner/name` and `HANDBOOK_REPOSITORY_URL` to its GitHub URL before building. Set `HANDBOOK_REF` to a commit or branch for source citations; it defaults to `main`. `HANDBOOK_SITE_URL` supplies the final canonical website URL.

## Review in the private testing repository

The **Handbook checks and website** workflow runs the repository gates, reference tests, report comparison and website build. Its **handbook-site-preview** artifact contains the generated site. Download and extract that artifact, then serve the extracted folder locally:

```bash
python -m http.server 8000 --bind 127.0.0.1
```

Use a local server so search and other browser assets load correctly. The artifact is a downloadable preview, not a hosted website. Access to a private repository's Actions artifacts follows repository access.

The testing repository keeps an imported public baseline for comparison. Review draft changes against that baseline before preparing a public release.

## Publish the reviewed public site

After review, transfer the selected changes to the public handbook repository. Review the changed files and apply the appropriate identifier checks before publication. The testing repository's history should stay private.

In the public repository, open **Settings → Pages** and choose **GitHub Actions** as the source. Then open **Actions → Handbook checks and website → Run workflow**, select `main`, and enable **Publish the public handbook to GitHub Pages**.

The deployment job is restricted to the named public repository, its main branch, a public visibility check and that explicit workflow input. Ordinary pushes build an artifact without publishing. The private testing repository cannot deploy through this workflow. If the public repository is renamed or transferred, update the deployment conditions and canonical URL together.

The public reading site is [the handbook on GitHub Pages](https://mouteee.github.io/autonomous-offensive-llm-handbook/). New content appears there after a successful deployment.

See [GitHub's Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) and [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) for the hosting and reading theme.
