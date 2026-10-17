# C programming examples

Two exercises are provided for each difficulty:

| Difficulty | Exercises |
| --- | --- |
| Warmup | [First C Program](exercises/hello-c/README.md), [Square an Integer](exercises/square-c/README.md) |
| Easy | [Sum Two Integers](exercises/sum-c/README.md), [Fibonacci Sequence](exercises/fibo-c/README.md) |
| Medium | [Palindrome Check](exercises/palindrome-c/README.md), [Sort Integers](exercises/sort-c/README.md) |
| Hard | [Matrix Multiplication](exercises/matrix-multiply-c/README.md), [Shortest Paths](exercises/shortest-path-c/README.md) |

Each exercise contains a subject (`README.md`), manifest (`exercise.yaml`),
SSH development image (`dev/`), standalone Python evaluator (`evaluator/`),
and a downloadable Markdown guide (`resources/guide.md`). Evaluators compile
C11 submissions and write schema version 1 reports to `/result/result.json`.
`WORKSPACE_DIR` and `RESULT_DIR` can override the default paths for local checks.

## Test suite

From the repository root, install the test tools in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install pytest PyYAML ruff
.venv/bin/python -m pytest -q courses/examples/tests
.venv/bin/ruff check courses/examples
```

The local tests need `gcc`. They run real C reference submissions, reject common
incorrect algorithms, check exact output and exit codes, exercise compiler and
runtime failures, validate the catalog/resources, and verify the published examples.
Reference solutions live under `tests/solutions/` and are not listed as resources.

To also build all development/evaluator images and run the evaluators inside the
repository's trusted sandbox, enable the Docker tests:

```sh
EVALOPS_EXAMPLE_DOCKER_TESTS=1 .venv/bin/python -m pytest -q -s courses/examples/tests
```

These Docker tests use temporary containers and image tags, remove them afterward,
and do not start or reset the Compose deployment. They check SSH readiness,
compilation as the student user, and passing/failing submissions against read-only
workspaces using the production evaluator runner.
