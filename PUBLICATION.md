# Publishing this handbook

Do not make the existing development repository public by changing its visibility. A clean working tree and a passing identifier scan say nothing about names or addresses retained in reachable Git history.

Publish a history-free snapshot instead:

```bash
git archive --format=tar --prefix=autonomous-offensive-llm-handbook/ HEAD > /tmp/autonomous-offensive-llm-handbook.tar
```

Inspect the extracted snapshot and run every release command from `README.md`. Before the first commit, initialize a new repository in the extracted tree, configure the approved public author identity, and put the owner's private employer/client/host/internal-scheme patterns in `scripts/.denylist`. The denylist is ignored by Git and must never be committed.

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

Only after that gate passes should the new public repository receive its first
commit. Do not push or mirror the private development refs, tags, reflogs or
object database into it. Re-run the private identifier sweep over the final
staging tree immediately before publishing. This is a publication-boundary
requirement, not a claim that the current history contains a secret.
