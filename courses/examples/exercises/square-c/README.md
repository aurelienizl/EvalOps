# Square an Integer in C

## File Tree

```text
square-c/
└── square.c (to submit)
```

## Goal

Read one integer `n` from standard input, where `-1000 <= n <= 1000`.
Print `n * n` followed by a newline. Do not print a prompt.

## Example

Input:

```text
-7
```

Output:

```text
49
```

## Instructions

1. Connect to your development environment over SSH.
2. Create `square.c` in `/home/student/square-c`.
3. Compile your program:
   ```sh
   cd ~/square-c
   gcc -std=c11 -Wall -Wextra square.c -o app
   ```
4. Run `./app` and check the example above and the boundary cases in the
   downloadable reference guide in **Resources**.
5. Click **Evaluate** on the platform.

The C standard library is allowed. Submit the source file; the evaluator builds
its own executable. It checks compilation, a zero exit status, and exact standard
output, including spaces and the final newline. Each execution has a two-second
limit. You have three evaluations per 60-minute window.
