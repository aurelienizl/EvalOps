# Sum Two Integers in C

## File Tree

```text
sum-c/
└── sum.c (to submit)
```

## Goal

Read two integers `a` and `b` from standard input. Each lies between
`-1000000000` and `1000000000`, inclusive. Print their sum followed by a
newline. Whitespace separates the input values; do not print a prompt.

## Example

Input:

```text
2 3
```

Output:

```text
5
```

## Instructions

1. Connect to your development environment over SSH.
2. Create the exercise directory with `mkdir -p ~/sum-c`, then create
   `sum.c` inside it.
3. Compile your program:
   ```sh
   cd ~/sum-c
   gcc -std=c11 -Wall -Wextra sum.c -o app
   ```
4. Run `./app` and check the example above and the boundary cases in the
   downloadable reference guide in **Resources**.
5. Click **Evaluate** on the platform.

The C standard library is allowed. Submit the source file; the evaluator builds
its own executable. It checks compilation, a zero exit status, and exact standard
output, including spaces and the final newline. Each execution has a two-second
limit. You have three evaluations per 60-minute window.
