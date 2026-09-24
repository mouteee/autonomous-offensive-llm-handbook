# Publishing this handbook

Do not make the private testing repository public by changing its visibility, and do not merge or mirror its branches into the public repository. A clean working tree and a passing identifier scan say nothing about names or addresses retained in reachable Git history.

Export one reviewed commit as a history-free file snapshot instead:

```bash
git archive --format=tar --prefix=autonomous-offensive-llm-handbook/ HEAD > /tmp/autonomous-offensive-llm-handbook.tar
```

Inspect the extracted snapshot and run every release command from `README.md`. Remove private review-only files from the release file list. Before the staging tree's first commit, initialize a new repository in that directory, configure the approved public author identity, and put the owner's private employer/client/host/internal-scheme patterns in `scripts/.denylist`. The denylist is ignored by Git and must never be committed.

Run the publication-only gate before the first commit:

```bash
git init
git config user.name "<approved public author name>"
git config user.email "<approved public or noreply author email>"
export PUBLICATION_AUTHOR_NAME="<the exact approved name above>"
export PUBLICATION_AUTHOR_EMAIL="<the exact approved email above>"
# privately create scripts/.denylist with at least one real operator pattern
bash scripts/publication_gate.sh .
```

The gate refuses a missing, empty or unreadable private denylist; a mismatch in
the configured author identity; any existing ref, tag, object or reflog; and any
identifier match. A green normal test suite is not a substitute for this gate.
The conference release builder also creates `handbook-source.zip` from the exact
tracked handbook commit and excludes Git metadata, ignored files and build
caches.

Only after that gate passes should the staging tree receive its first commit.
For an existing public repository, create a release branch from **public**
`main`, copy only the audited staging commit's files into it, and make a new
public commit with the approved identity. The release branch must have the
public repository as its only ancestry; never merge the staging commit or any
private development ref. Review the complete public diff, run the tests and
site checks there, and re-run the private identifier sweep over the final
release tree immediately before pushing it. Use a pull request to review and
merge that content-only commit. For a new public repository, the audited
staging commit can instead be its first commit.

Do not push or mirror private development refs, tags, reflogs or object
databases into either public path. This is a publication-boundary requirement,
not a claim that the current history contains a secret.
