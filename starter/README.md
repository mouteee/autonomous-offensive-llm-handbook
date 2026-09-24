# The starter exercises

These files are yours. Each `lessonNN.py` opens with working imports and a
function body that raises `NotImplementedError` with instructions; the paired
`lessonNN_test.py` is that lesson's learner-owned completion check, and it
fails on a fresh clone on purpose. Passing it requires your edit, not the
reference implementation's.

Run one exercise at a time, from the repository root:

    python3 -m pytest starter/lesson02_test.py -q

The exercises share one continuing fictional thread: a harmless
`inspect_metadata` fixture tool that you declare in lesson 2's policy, propose
through lesson 4's provider, and dispatch to a capture in lesson 5. Worked
solutions are in `starter/solutions/`. Read them after your attempt, or run
a test against them with `STARTER_SOLUTIONS=1` to see the finished behavior.
Nothing here touches a network; the reference suite under `tests/` stays green
whether or not you have started.
