# Shortest Paths in C

## File Tree

```text
shortest-path-c/
└── shortest_path.c (to submit)
```

## Goal

Read `n m source`, where `1 <= n <= 100`, `0 <= m <= 1000`, and
`0 <= source < n`. Vertices are numbered from 0 to `n - 1`. Next read `m`
directed edges, each as `from to weight`, where endpoints are valid vertices
and `0 <= weight <= 1000000`. Parallel edges and self-loops are allowed.
All input satisfies these constraints.

Print the shortest distance from `source` to every vertex in vertex order,
using `-1` for unreachable vertices. The distance to the source is zero.
Separate distances with single spaces, with no leading or trailing space,
and end with a newline. Whitespace separates all input tokens.

## Example

Input:

```text
4 4 0
0 1 5
0 2 1
2 1 2
1 3 1
```

Output:

```text
0 3 1 4
```

## Instructions

1. Connect to your development environment over SSH.
2. Create `shortest_path.c` in `/home/student/shortest-path-c`.
3. Compile your program:
   ```sh
   cd ~/shortest-path-c
   gcc -std=c11 -Wall -Wextra shortest_path.c -o app
   ```
4. Run `./app` and check the example above and the boundary cases in the
   downloadable reference guide in **Resources**.
5. Click **Evaluate** on the platform.

The C standard library is allowed. Submit the source file; the evaluator builds
its own executable. It checks compilation, a zero exit status, and exact standard
output, including spaces and the final newline. Each execution has a two-second
limit. You have three evaluations per 60-minute window.
